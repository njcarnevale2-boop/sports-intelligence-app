"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import FreshnessBadge from "@/components/ui/freshness-badge";
import { fetchJson } from "./lib/api";
import { trackAnalyticsEvent } from "./lib/analytics";
import {
  buildLineStatusMessage,
  conciseWhySiaLikesIt,
  formatBetRange,
  formatModelCushion,
  modelAdvantageLabel,
  modelAdvantageSubtext,
  modelCushionSubtext,
} from "./lib/home-decision-clarity";

const HOME_DECISION_BOARD_TIMEOUT_MS = 30000;

type QuoteWarnings = {
  isStale?: boolean;
  limitedDepth?: boolean;
};

type DecisionBoardItem = {
  rank: number;
  eventId: string;
  marketFamily: string;
  selection: string;
  line: number | null;
  price: number | null;
  sportsbook: string | null;
  bestAvailableLine: number | null;
  bestAvailablePrice: number | null;
  bestAvailableSportsbook: string | null;
  recommendedPlayableTo: number | null;
  recommendedPlayableToStatus?: string | null;
  recommendedPlayableToReason?: string | null;
  playableTo: number | null;
  modelProbability: number | null;
  marketImpliedProbability: number | null;
  edge: number | null;
  expectedValue: number | null;
  confidence: number | null;
  marketDepth: string;
  marketCoverageBookCount?: number | null;
  marketCoverageStatus?: string | null;
  quoteFreshness: string;
  gameStartTime: string;
  quoteLastUpdated?: string | null;
  recommendationStatus: string;
  productionEligible: boolean;
  whySiaLikesIt: string;
  riskFactors: string[];
  invalidationReason?: string | null;
  quoteWarnings?: QuoteWarnings;
};

type NoBetState = {
  headline: string;
  summary: string;
  closestOpportunity?: {
    eventId?: string;
    selection?: string;
    distanceFromTrigger?: string | null;
  } | null;
};

type GameDecision = {
  eventId: string;
  matchup: string;
  awayAbbreviation: string;
  homeAbbreviation: string;
  commenceTime: string;
  status: "APPROVED" | "NO_PLAY" | "PENDING";
  reason: string;
  selection?: string | null;
};

type DecisionBoardResponse = {
  week?: number;
  projectionReadiness?: string;
  projectionReadinessReason?: string;
  officialPublicationStatus?: string;
  dataStatus?: string;
  lastUpdated?: string | null;
  snapshotId?: string;
  decisionBoard: DecisionBoardItem[];
  count: number;
  officialMarketsDisplayed: string[];
  noBetState?: NoBetState | null;
  gameDecisions?: GameDecision[];
  gameDecisionSummary?: { approved: number; noPlay: number; pending: number; scheduled: number };
  crossMarketComparable: boolean;
  universalSia3: string;
};

type GameSummary = {
  eventId: string;
  awayTeam: string;
  homeTeam: string;
  awayAbbreviation?: string | null;
  homeAbbreviation?: string | null;
  commenceTime: string;
  spread?: number | null;
  total?: number | null;
  recommendation?: string | null;
  qualificationStatus?: string | null;
  betStatus?: string | null;
  bestOpportunity?: string | null;
  bestOpportunityDetail?: {
    market?: string;
    side?: string;
    pick?: string;
    point?: number | null;
    price?: number | null;
    sportsbook?: string | null;
  } | null;
  sportsIntelligenceScore?: number | null;
  marketDataStatus?: string;
};

type GamesResponse = {
  count: number;
  availableWeeks: number[];
  availableDates: string[];
  dataStatus?: { marketIntelligence?: string };
  games: GameSummary[];
};

type WatchlistItem = {
  eventId: string;
  matchup: string;
  status: string;
  currentLine: string;
  summary: string;
  detail?: string | null;
  actionLabel: string;
};

function formatSigned(value: number | null | undefined) {
  if (value == null) return "Unavailable";
  return value > 0 ? `+${value}` : `${value}`;
}

function coverageStatusLabel(status: string | null | undefined) {
  const normalized = String(status || "").toUpperCase();
  if (normalized === "DEEP") return "BROAD COVERAGE";
  if (normalized === "MODERATE") return "MODERATE COVERAGE";
  if (normalized === "THIN") return "LIMITED COVERAGE";
  if (normalized === "SINGLE_BOOK") return "SINGLE BOOK";
  return "NO COVERAGE";
}

function marketCoverageValue(item: DecisionBoardItem) {
  const count = item.marketCoverageBookCount;
  if (count == null) {
    return coverageStatusLabel(item.marketCoverageStatus || item.marketDepth);
  }
  if (count <= 0) return "NO COVERAGE";
  return `${count} ${count === 1 ? "SPORTSBOOK" : "SPORTSBOOKS"}`;
}

function freshnessLabel(freshness: string) {
  const normalized = String(freshness || "").toUpperCase();
  if (normalized === "FRESH") return "CURRENT";
  if (normalized === "WARM") return "RECENT";
  if (normalized === "STALE") return "CHECK CURRENT LINE";
  return "CHECK CURRENT LINE";
}

function executableQuote(item: DecisionBoardItem) {
  const line = item.line != null ? formatSigned(item.line) : null;
  const price = item.price != null ? formatSigned(item.price) : null;
  const book = item.sportsbook || "Unavailable";
  if (line && price) return `${line} (${price}) · ${book}`;
  if (price) return `${price} · ${book}`;
  if (line) return `${line} · ${book}`;
  return `Unavailable · ${book}`;
}

function matchupLabel(game?: GameSummary | null) {
  if (!game) return "Matchup unavailable";
  const away = game.awayAbbreviation || game.awayTeam || "Away";
  const home = game.homeAbbreviation || game.homeTeam || "Home";
  return `${away} @ ${home}`;
}

function marketLineLabel(game?: GameSummary | null) {
  if (!game) return "Current line unavailable";
  if (game.spread != null) {
    const home = game.homeAbbreviation || game.homeTeam || "Home";
    return `${home} ${formatSigned(game.spread)}`;
  }
  if (game.total != null) return `Total ${game.total.toFixed(1)}`;
  return "Current line unavailable";
}

export default function Home() {
  const [board, setBoard] = useState<DecisionBoardResponse | null>(null);
  const [games, setGames] = useState<GameSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [gamesLoading, setGamesLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        setError("");
        void trackAnalyticsEvent("DecisionBoardViewed", { page: "home" });
        const payload = await fetchJson<DecisionBoardResponse>(
          "/api/decision-board?limit=3",
          undefined,
          HOME_DECISION_BOARD_TIMEOUT_MS
        );
        if (cancelled) return;
        setBoard(payload);
        setGamesLoading(true);

        try {
          const gamesPayload = await fetchJson<GamesResponse>(
            payload.week != null ? `/api/games?week=${payload.week}` : "/api/games",
            undefined,
            HOME_DECISION_BOARD_TIMEOUT_MS
          );
          const decisionByEventId = new Map((payload.gameDecisions || []).map((decision) => [decision.eventId, decision]));
          const projectionCurrent = String(payload.projectionReadiness || "").toUpperCase() === "CURRENT";
          const officialPublished = String(payload.officialPublicationStatus || "").toUpperCase() === "PUBLISHED";
          if (!cancelled) {
            setGames((gamesPayload.games || []).map((game): GameSummary => {
              const decision = decisionByEventId.get(game.eventId);
              const approved = projectionCurrent && officialPublished && decision?.status === "APPROVED";
              return {
                ...game,
                bestOpportunity: approved ? decision.selection ?? null : null,
                qualificationStatus: approved ? "QUALIFIED" : decision?.status === "NO_PLAY" && projectionCurrent ? "NO_PLAY" : "PENDING",
                betStatus: approved ? "APPROVED" : decision?.status === "NO_PLAY" && projectionCurrent ? "NO_PLAY" : "PENDING",
              };
            }));
          }
        } catch {
          if (!cancelled) {
            setGames([]);
          }
        } finally {
          if (!cancelled) {
            setGamesLoading(false);
          }
        }
      } catch (err) {
        console.error(err);
        setError("Unable to load SIA decision board.");
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, []);

  const projectionCurrent = String(board?.projectionReadiness || "").toUpperCase() === "CURRENT";
  const officialPublished = String(board?.officialPublicationStatus || "").toUpperCase() === "PUBLISHED";
  const items = projectionCurrent && officialPublished ? board?.decisionBoard || [] : [];
  const primary = items[0] || null;
  const alsoWorthBetting = items.slice(1, 3);
  const gameByEventId = useMemo(() => new Map(games.map((game) => [game.eventId, game])), [games]);

  const watchlist = useMemo(() => {
    const decisions = new Map((board?.gameDecisions || []).map((decision) => [decision.eventId, decision]));
    return games.map((game) => {
      const decision = decisions.get(game.eventId);
      const approved = projectionCurrent && officialPublished && decision?.status === "APPROVED";
      const status = !projectionCurrent || (decision?.status === "APPROVED" && !officialPublished)
        ? "PENDING"
        : decision?.status || "PENDING";
      return {
        eventId: game.eventId,
        matchup: matchupLabel(game),
        status,
        currentLine: approved ? decision.selection || "Official pick" : !projectionCurrent ? "Projection unavailable" : status === "NO_PLAY" ? "No play" : "No approved pick",
        summary: !projectionCurrent
          ? "Current model projections are unavailable. No model pick or Official decision is shown."
          : decision?.status === "APPROVED" && !officialPublished
            ? "Official publication has not been confirmed."
            : decision?.reason || "No approved game decision is available for this scheduled matchup.",
        detail: null,
        actionLabel: "VIEW GAME INTEL",
      };
    });
  }, [board?.gameDecisions, games, officialPublished, projectionCurrent]);

  const title = useMemo(() => {
    if (!projectionCurrent) return "Model Analysis Pending";
    if (items.length === 0) return "No High-Conviction Bets";
    if (items.length === 1) return "Top Opportunity";
    return "Top Opportunities";
  }, [items.length, projectionCurrent]);

  const readLine = !projectionCurrent
    ? `Current model projections are unavailable or pending (${board?.projectionReadinessReason || "readiness not confirmed"}). SIA is not presenting current model analysis or Official picks.`
    : !officialPublished
      ? "Official picks are pending publication. No candidate is shown as an Official pick."
      : primary
    ? `SIA found ${items.length} production bet${items.length === 1 ? "" : "s"} worth acting on right now.`
    : board?.noBetState?.summary || "SIA does not currently see a production-quality edge worth taking.";
  const primaryLineStatus = primary
    ? buildLineStatusMessage(primary, primary.quoteFreshness, primary.quoteLastUpdated ?? board?.lastUpdated)
    : null;

  if (loading) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:px-10">
          <p className="text-sm text-zinc-500">Loading SIA decision board...</p>
        </div>
      </main>
    );
  }

  if (error || !board) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:px-10">
          <p className="text-sm text-rose-400">{error || "Unable to load decision board."}</p>
        </div>
      </main>
    );
  }

  return (
    <main className="relative min-h-screen overflow-hidden bg-[#070A0F] text-white">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute left-[-8%] top-[-12%] h-72 w-72 rounded-full bg-cyan-500/10 blur-3xl" />
        <div className="absolute right-[-6%] top-[10%] h-80 w-80 rounded-full bg-amber-400/10 blur-3xl" />
      </div>

      <header className="relative border-b border-white/[0.06] bg-black/10 backdrop-blur-sm">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-6 py-5 lg:px-10 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-[11px] font-medium uppercase tracking-[0.22em] text-zinc-600">SIA COMMAND CENTER</p>
            <h1 className="mt-1 text-xl font-semibold tracking-tight">AI Sports Betting Analyst</h1>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {board.dataStatus ? <FreshnessBadge status={board.dataStatus} lastUpdated={board.lastUpdated} label="Market" /> : null}
            <Badge variant="outline" className="border-white/[0.08] bg-white/[0.03] text-zinc-300">{board.officialMarketsDisplayed.join(", ") || "SPREAD ONLY"}</Badge>
            <Badge variant="outline" className="border-white/[0.08] bg-white/[0.03] text-zinc-300">Universal SIA3 {board.universalSia3}</Badge>
            <Link href="/games">
              <Button variant="outline" className="h-10 border-white/10 bg-transparent text-white hover:bg-white/[0.05]">Games Hub</Button>
            </Link>
          </div>
        </div>
      </header>

      <div className="relative mx-auto max-w-6xl px-6 py-8 lg:px-10">
        <section className="rounded-3xl border border-white/[0.08] bg-[#0B1119]/95 p-6 shadow-[0_24px_80px_rgba(0,0,0,0.28)] md:p-8">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="max-w-3xl">
              <p className="text-xs uppercase tracking-[0.22em] text-zinc-600">SIA&apos;s Read</p>
              <h2 className="mt-2 text-3xl font-semibold tracking-tight md:text-4xl">{title}</h2>
              <p className="mt-3 text-sm leading-6 text-zinc-400">{readLine}</p>
              <p className="mt-2 text-xs uppercase tracking-[0.18em] text-zinc-600">
                {board.week != null ? `Week ${board.week}` : "Current slate"} · {items.length} official production pick{items.length === 1 ? "" : "s"}
              </p>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <Badge variant="outline" className={officialPublished ? "border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-300" : "border-amber-400/20 bg-amber-400/[0.05] text-amber-300"}>{officialPublished ? "Production Bets Only" : projectionCurrent ? "Publication Pending" : "Projection Pending"}</Badge>
              <Badge variant="outline" className="border-white/[0.08] bg-white/[0.03] text-zinc-300">{gamesLoading ? "Watchlist Updating" : `${watchlist.length} Watch Items`}</Badge>
            </div>
          </div>

          {primary ? (
            <article className="mt-6 rounded-3xl border border-emerald-400/20 bg-gradient-to-br from-white/[0.05] to-black/25 p-5 md:p-6">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-[11px] uppercase tracking-[0.2em] text-emerald-300">#1 BET</p>
                  <h3 className="mt-2 text-2xl font-semibold text-white md:text-3xl">{matchupLabel(gameByEventId.get(primary.eventId))}</h3>
                  <p className="mt-1 text-sm text-zinc-300">{primary.selection} · {primary.recommendationStatus}</p>
                </div>
                <Badge className="bg-emerald-400 text-black hover:bg-emerald-300">BET</Badge>
              </div>

              <div className="mt-5 grid gap-5 lg:grid-cols-[1.15fr_0.85fr]">
                <div className="space-y-4">
                  <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                    <InfoTile label="BEST EXECUTABLE" value={executableQuote(primary)} />
                    <InfoTile label="BET RANGE" value={formatBetRange(primary)} subtext="Based on the current observed executable line." />
                    <InfoTile label="MODEL CUSHION" value={formatModelCushion(primary)} subtext={modelCushionSubtext(primary)} />
                    <InfoTile
                      label="MODEL ADVANTAGE"
                      value={modelAdvantageLabel(primary)}
                      subtext={modelAdvantageSubtext(primary)}
                    />
                    <InfoTile
                      label="MARKET COVERAGE"
                      value={marketCoverageValue(primary)}
                      subtext={coverageStatusLabel(primary.marketCoverageStatus || primary.marketDepth)}
                    />
                    <InfoTile label="QUOTE FRESHNESS" value={freshnessLabel(primary.quoteFreshness)} />
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="rounded-2xl border border-white/[0.08] bg-black/20 p-4">
                      <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-600">Why SIA Likes It</p>
                      <p className="mt-2 text-sm leading-6 text-zinc-300">{conciseWhySiaLikesIt(primary)}</p>
                    </div>
                    <div className="rounded-2xl border border-amber-400/20 bg-amber-400/[0.05] p-4">
                      <p className="text-[10px] uppercase tracking-[0.16em] text-amber-300">Biggest Risk</p>
                      <p className="mt-2 text-sm leading-6 text-amber-100">{primary.invalidationReason || primary.riskFactors[0] || "Material market movement can invalidate this opportunity."}</p>
                    </div>
                  </div>
                </div>

                <div className="space-y-3 rounded-2xl border border-white/[0.08] bg-black/20 p-4">
                  <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-600">Verdict</p>
                  <p className="text-2xl font-semibold text-white">BET</p>
                  <p className="text-sm leading-6 text-zinc-300">
                    SIA&apos;s best current wager is {primary.selection} at {primary.sportsbook || "an available book"}. This recommendation is anchored to the currently observed executable quote.
                  </p>
                  <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-4 text-sm text-zinc-300">
                    <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-600">Current Line</p>
                    <p className="mt-2 text-white">{primaryLineStatus?.heading ?? "CHECK CURRENT LINE"}</p>
                    <p className="mt-1">{primaryLineStatus?.detail ?? "This quote may be outdated. Confirm the current line and price before betting."}</p>
                  </div>
                  <div className="flex flex-wrap gap-2 pt-1">
                    <Link href={`/games/${primary.eventId}`}>
                      <Button className="h-9 bg-white px-4 text-black hover:bg-zinc-200">Game Intel</Button>
                    </Link>
                    <Link href={`/games/${primary.eventId}?ask=${encodeURIComponent("Why does SIA like this bet?")}`}>
                      <Button variant="outline" className="h-9 border-white/10 bg-transparent px-4 text-white hover:bg-white/[0.05]">Ask SIA</Button>
                    </Link>
                  </div>
                </div>
              </div>
            </article>
          ) : (
            <article className="mt-6 rounded-3xl border border-dashed border-white/[0.12] bg-black/20 p-5 md:p-6">
              <p className="text-[11px] uppercase tracking-[0.2em] text-zinc-600">{!projectionCurrent ? "PROJECTION PENDING" : !officialPublished ? "PUBLICATION PENDING" : "NO BET"}</p>
              <h3 className="mt-2 text-2xl font-semibold text-white">
                {!projectionCurrent
                  ? "Current model projections are unavailable."
                  : !officialPublished
                    ? "Official picks are pending publication."
                    : "SIA does not currently see a production-quality edge worth taking."}
              </h3>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-zinc-400">
                {!projectionCurrent
                  ? `Readiness: ${board.projectionReadinessReason || "PROJECTION_NOT_CURRENT"}. No current model analysis or Official picks are shown.`
                  : !officialPublished
                    ? "No candidate is shown as an Official pick until the publication gate passes."
                    : board.noBetState?.summary || "SIA is waiting for a better price, a stronger edge, or more favorable market movement before publishing a bet."}
              </p>

              {projectionCurrent && officialPublished && board.noBetState?.closestOpportunity ? (
                <div className="mt-5 rounded-2xl border border-white/[0.08] bg-white/[0.03] p-4">
                  <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-600">Closest legitimate opportunity</p>
                  <div className="mt-2 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                    <div>
                      <p className="text-lg font-semibold text-white">{board.noBetState.closestOpportunity.selection || "Closest setup"}</p>
                      <p className="mt-1 text-sm text-zinc-400">{board.noBetState.closestOpportunity.distanceFromTrigger || "SIA is waiting for a better number."}</p>
                    </div>
                    {board.noBetState.closestOpportunity.eventId ? (
                      <Link href={`/games/${board.noBetState.closestOpportunity.eventId}`}>
                        <Button className="h-9 bg-white px-4 text-black hover:bg-zinc-200">Game Intel</Button>
                      </Link>
                    ) : null}
                  </div>
                </div>
              ) : null}
            </article>
          )}

          {alsoWorthBetting.length > 0 ? (
            <section className="mt-8">
              <div className="flex items-end justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.2em] text-zinc-600">Also Worth Betting</p>
                  <h3 className="mt-2 text-xl font-semibold tracking-tight text-white">Qualified production picks #2 and #3</h3>
                </div>
              </div>

              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                {alsoWorthBetting.map((item) => {
                  const game = gameByEventId.get(item.eventId);
                  const status = buildLineStatusMessage(item, item.quoteFreshness, item.quoteLastUpdated ?? board.lastUpdated);
                  return (
                    <article key={`${item.eventId}-${item.rank}`} className="rounded-2xl border border-white/[0.08] bg-black/20 p-5">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-600">#{item.rank}</p>
                        <Badge variant="outline" className="border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-300">BET</Badge>
                      </div>
                      <h4 className="mt-3 text-lg font-semibold text-white">{matchupLabel(game)}</h4>
                      <p className="mt-1 text-sm text-zinc-300">{item.selection} · {item.recommendationStatus}</p>

                      <div className="mt-4 grid gap-3 sm:grid-cols-2">
                        <MiniStat label="BEST PRICE" value={executableQuote(item)} />
                        <MiniStat label="BET RANGE" value={formatBetRange(item)} subtext="Based on the current observed executable line." />
                        <MiniStat label="MODEL CUSHION" value={formatModelCushion(item)} subtext={modelCushionSubtext(item)} />
                        <MiniStat
                          label="MODEL ADVANTAGE"
                          value={modelAdvantageLabel(item)}
                          subtext={modelAdvantageSubtext(item)}
                        />
                        <MiniStat label="QUOTE FRESHNESS" value={freshnessLabel(item.quoteFreshness)} />
                        <MiniStat
                          label="MARKET COVERAGE"
                          value={marketCoverageValue(item)}
                          subtext={coverageStatusLabel(item.marketCoverageStatus || item.marketDepth)}
                        />
                      </div>

                      <div className="mt-3 rounded-xl border border-white/[0.08] bg-white/[0.03] p-3">
                        <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-600">Current Line</p>
                        <p className="mt-2 text-sm text-white">{status.heading}</p>
                        <p className="mt-1 text-sm leading-6 text-zinc-300">{status.detail}</p>
                      </div>

                      <div className="mt-4 rounded-xl border border-white/[0.08] bg-white/[0.03] p-3">
                        <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-600">Why SIA Likes It</p>
                        <p className="mt-2 text-sm leading-6 text-zinc-300">{conciseWhySiaLikesIt(item)}</p>
                      </div>

                      <div className="mt-3 rounded-xl border border-amber-400/20 bg-amber-400/[0.04] p-3">
                        <p className="text-[10px] uppercase tracking-[0.16em] text-amber-300">Biggest Risk</p>
                        <p className="mt-2 text-sm text-amber-200">{item.invalidationReason || item.riskFactors[0] || "Material market movement can invalidate this opportunity."}</p>
                      </div>

                      <div className="mt-4 flex flex-wrap gap-2">
                        <Link href={`/games/${item.eventId}`}>
                          <Button className="h-9 bg-white px-4 text-black hover:bg-zinc-200">Game Intel</Button>
                        </Link>
                        <Link href={`/games/${item.eventId}?ask=${encodeURIComponent("Why does SIA like this bet?")}`}>
                          <Button variant="outline" className="h-9 border-white/10 bg-transparent px-4 text-white hover:bg-white/[0.05]">Ask SIA</Button>
                        </Link>
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          ) : null}

          <section className="mt-8">
            <div className="flex items-end justify-between gap-3">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-zinc-600">Game-day decisions</p>
                <h3 className="mt-2 text-xl font-semibold tracking-tight text-white">Every scheduled game has a current status</h3>
              </div>
              {gamesLoading ? <p className="text-xs uppercase tracking-[0.16em] text-zinc-600">Updating</p> : null}
            </div>

            {watchlist.length > 0 ? (
              <div className="mt-4 grid gap-4 lg:grid-cols-3">
                {watchlist.map((item) => (
                  <article key={item.eventId + item.currentLine} className="rounded-2xl border border-white/[0.08] bg-black/20 p-5">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-600">{item.status === "APPROVED" ? "OFFICIAL DECISION" : "GAME DECISION"}</p>
                      <Badge variant="outline" className={item.status === "APPROVED" ? "border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-300" : item.status === "NO_PLAY" ? "border-white/[0.08] bg-white/[0.03] text-zinc-300" : "border-amber-400/20 bg-amber-400/[0.05] text-amber-300"}>{item.status}</Badge>
                    </div>
                    <h4 className="mt-3 text-lg font-semibold text-white">{item.matchup}</h4>
                    <p className="mt-1 text-sm text-zinc-300">{item.currentLine}</p>
                    <p className="mt-3 text-sm leading-6 text-zinc-400">{item.summary}</p>
                    {item.detail ? <p className="mt-2 text-sm text-zinc-300">{item.detail}</p> : null}
                    <div className="mt-4 flex flex-wrap gap-2">
                      <Link href={`/games/${item.eventId}`}>
                        <Button className="h-9 bg-white px-4 text-black hover:bg-zinc-200">{item.actionLabel}</Button>
                      </Link>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="mt-4 rounded-2xl border border-white/[0.08] bg-black/20 p-5 text-sm text-zinc-400">
                {projectionCurrent
                  ? "SIA has no additional scheduled-game decisions to display."
                  : "No current game decisions are available. The scheduled slate remains visible, but model analysis and Official picks are pending."}
              </div>
            )}
          </section>
        </section>
      </div>
    </main>
  );
}

function InfoTile({ label, value, subtext }: { label: string; value: string; subtext?: string }) {
  return (
    <div className="rounded-2xl border border-white/[0.08] bg-black/20 p-4">
      <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-600">{label}</p>
      <p className="mt-2 text-sm font-semibold text-white">{value}</p>
      {subtext ? <p className="mt-1 text-xs leading-5 text-zinc-500">{subtext}</p> : null}
    </div>
  );
}

function MiniStat({ label, value, subtext }: { label: string; value: string; subtext?: string }) {
  return (
    <div className="rounded-xl border border-white/[0.08] bg-white/[0.03] p-3">
      <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-600">{label}</p>
      <p className="mt-2 text-sm text-zinc-200">{value}</p>
      {subtext ? <p className="mt-1 text-xs leading-5 text-zinc-500">{subtext}</p> : null}
    </div>
  );
}
