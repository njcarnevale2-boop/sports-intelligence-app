"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fetchJson } from "../../lib/api";
import { addToCard as addToCardHelper } from "@/lib/add-to-card";
import {
  formatTravelMiles,
  formatTravelShift,
  getInjuryFreshness,
  getRestLabel,
  hasScheduleContext,
  type InjuryContext,
  type ScheduleContext,
} from "@/app/lib/page-context";
import Tooltip from "@/components/ui/tooltip";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type GameProjection = {
  eventId: string;
  commenceTime: string;
  matchup: string;
  awayTeam: string;
  homeTeam: string;
  teamPower: { away: number; home: number; differenceHomeMinusAway: number };
  model: { marginHome: number; total: number; projectedScore: { away: number; home: number } };
  market: { marginHome: number; homeSpread: number; total: number };
  spreadAnalysis: { edgePoints: number; homeCoverProbability: number; homeCoverFairOdds: number };
};

type MarketIntelligence = {
  score: number;
  grade: string;
  signal: string;
  booksTracked: number;
  booksMoving: number;
  steamBooks: number;
  supportingBooks: number;
  opposingBooks: number;
  consensus: number;
  largestPointMove: number;
  largestPriceMove: number;
  marketSupport: boolean;
  snapshots: number;
};

type SportsIntelligenceScore = {
  score: number;
  grade: string;
  stars: number;
  recommendation: string;
  components: {
    modelEdge: number;
    expectedValue: number;
    confidence: number;
    marketIntelligence: number;
    dataCompleteness: number;
  };
  reasons: string[];
};

type Opportunity = {
  id: string;
  eventId: string;
  commenceTime: string;
  matchup: string;
  awayTeam: string;
  homeTeam: string;
  pick: string;
  book: string;
  market: string;
  side: string;
  point: number;
  price: number;
  modelProbability: number;
  impliedProbability: number;
  fairOdds: number;
  edge: number;
  evPerDollar: number;
  kellyFull: number;
  kelly20: number;
  recommendation: string;
  confidence: number;
  dataCompleteness: number;
  rank: number;
  marketIntelligence: MarketIntelligence;
  sportsIntelligenceScore: SportsIntelligenceScore;
  injuryContext?: InjuryContext;
};

type IntelligenceReport = {
  eventId: string;
  betStatus: string;
  qualificationStatus: string;
  qualificationReasons: string[];
  currentLean: string;
  confidence?: number | null;
  currentMarket?: {
    spread?: string | number | null;
    total?: number | null;
    sportsbook?: string | null;
    price?: number | null;
  };
  whySummary: string;
  betTrigger: {
    available: boolean;
    message: string;
    monitor?: string | null;
    qualifiedAt?: string | null;
  };
};

type WeatherStatus = { dataStatus?: string; lastUpdated?: string | null };

type SocialSignal = {
  signalId: string;
  timestamp: string;
  team: string;
  player?: string | null;
  position?: string | null;
  category: string;
  severity: string;
  sourceName: string;
  sourceHandle: string;
  sourceType: string;
  sourceCredibility: number;
  textSummary: string;
  corroborationCount: number;
  confidence: number;
  status: string;
  estimatedPointImpact: number;
  marketRelevance: string;
  gameImpact: number;
  eventId?: string | null;
  provider: string;
  isLive: boolean;
};

type SocialGameContext = {
  available?: boolean;
  eventId: string;
  awayTeam?: string;
  homeTeam?: string;
  awaySocialScore?: number;
  homeSocialScore?: number;
  netSocialAdvantage?: number;
  keySignals: SocialSignal[];
  confidence?: number;
  summary?: string;
  provider: string;
  isLive: boolean;
  dataStatus: string;
  sourcesActive?: number;
  signalsDetected?: number;
  corroboratedSignals?: number;
  officialSignals?: number;
  lastIngestion?: string | null;
  errors?: string[];
  reason?: string;
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatKickoff(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "TBD";
  return d.toLocaleString("en-US", {
    weekday: "short", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit", timeZoneName: "short",
  });
}

function signedOdds(n: number) {
  return n > 0 ? `+${n}` : `${n}`;
}

function formatHomeSpreadLabel(homeTeam: string, spread: number | null | undefined) {
  if (spread == null) return "Unavailable";
  return `${homeTeam} ${spread > 0 ? `+${spread}` : spread}`;
}

function scoreTone(score?: number | null) {
  if (score == null) return "text-zinc-400";
  if (score >= 85) return "text-emerald-400";
  if (score >= 75) return "text-sky-400";
  return "text-amber-400";
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function GameIntelligencePage() {
  const params = useParams<{ eventId: string }>();
  const eventId = params.eventId;

  const [projection, setProjection] = useState<GameProjection | null>(null);
  const [context, setContext] = useState<ScheduleContext | null>(null);
  const [opportunity, setOpportunity] = useState<Opportunity | null>(null);
  const [weather, setWeather] = useState<WeatherStatus | null>(null);
  const [injury, setInjury] = useState<InjuryContext | null>(null);
  const [social, setSocial] = useState<SocialGameContext | null>(null);
  const [intelligenceReport, setIntelligenceReport] = useState<IntelligenceReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [added, setAdded] = useState(false);
  const [snapshotError, setSnapshotError] = useState("");

  useEffect(() => {
    if (!eventId) return;

    async function load() {
      try {
        setLoading(true);
        setError("");

        // Primary game data (required)
        const proj = await fetchJson<GameProjection>(`/api/games/${eventId}`);
        setProjection(proj);

        // Check localStorage for existing bet on this event
        try {
          const raw = localStorage.getItem("sports-intelligence-card");
          if (raw) {
            const card = JSON.parse(raw) as Array<{ eventId?: string }>;
            setAdded(card.some((b) => b.eventId === eventId));
          }
        } catch { /* ignore */ }

        // Parallel non-fatal requests
        const [ctxResult, oppResult, weatherResult, injuryResult, socialResult] = await Promise.allSettled([
          fetchJson<ScheduleContext>(`/api/games/${eventId}/context`),
          fetchJson<{ eventId: string; opportunity: Opportunity | null; intelligenceReport?: IntelligenceReport }>(`/api/games/${eventId}/opportunity`),
          fetchJson<WeatherStatus>(`/api/games/${eventId}/weather`),
          fetchJson<{ injuryContext: InjuryContext }>(`/api/games/${eventId}/injuries`),
          fetchJson<SocialGameContext>(`/api/games/${eventId}/social-intelligence`),
        ]);

        if (ctxResult.status === "fulfilled") setContext(ctxResult.value);
        if (oppResult.status === "fulfilled") {
          setOpportunity(oppResult.value.opportunity);
          if (oppResult.value.intelligenceReport) {
            setIntelligenceReport(oppResult.value.intelligenceReport);
          }
        }
        if (weatherResult.status === "fulfilled") setWeather(weatherResult.value);
        if (injuryResult.status === "fulfilled") setInjury(injuryResult.value.injuryContext);
        if (socialResult.status === "fulfilled") setSocial(socialResult.value);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "";
        setError(msg.includes("404") ? "Game not found." : "Unable to load game intelligence.");
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, [eventId]);

  async function handleAddToCard() {
    if (!opportunity) return;
    setSnapshotError("");
    const result = await addToCardHelper(opportunity as Record<string, unknown>);
    if (result.success) {
      setAdded(true);
    } else {
      setAdded(true);
      setSnapshotError(result.error);
    }
  }

  // ---------------------------------------------------------------------------
  // Loading / error states
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-5xl px-6 py-16 lg:px-10">
          <p className="text-sm text-zinc-500">Loading game intelligence…</p>
        </div>
      </main>
    );
  }

  if (error || !projection) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-5xl px-6 py-16 lg:px-10">
          <Link href="/games" className="text-sm text-zinc-500 hover:text-white">← Games</Link>
          <p className="mt-6 text-red-400">{error || "Game not found."}</p>
        </div>
      </main>
    );
  }

  const si = opportunity?.sportsIntelligenceScore;
  const mi = opportunity?.marketIntelligence;
  const hasContext = hasScheduleContext(context);
  const restLabel = getRestLabel(context?.rest);
  const travelMiles = formatTravelMiles(context?.travel);
  const travelShift = formatTravelShift(context?.travel);
  const injuryFreshness = getInjuryFreshness(injury);
  const topSocialSignals = social?.keySignals?.slice(0, 3) ?? [];
  const topNoBetReasons = intelligenceReport?.qualificationReasons?.slice(0, 3) ?? [];

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-5xl px-6 py-10 lg:px-10 space-y-8">

        {/* NAV */}
        <div className="flex flex-wrap items-center justify-between gap-4">
          <Link href="/games" className="text-sm text-zinc-500 transition hover:text-white">
            ← Games
          </Link>
          {typeof context?.week === "number" && typeof context?.season === "number" && (
            <Badge variant="outline" className="border-white/10 bg-white/[0.03] text-zinc-400">
              Week {context.week} · {context.season} Season
            </Badge>
          )}
        </div>

        {/* HEADER */}
        <section className="rounded-[32px] border border-white/[0.08] bg-[#0B1119] p-8">
          <p className="text-[10px] uppercase tracking-[0.28em] text-zinc-600">
            {formatKickoff(projection.commenceTime)}
          </p>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight">
            {projection.awayTeam} @ {projection.homeTeam}
          </h1>

          {/* Model projected score */}
          <div className="mt-6 flex items-center gap-6">
            <div className="text-center">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600">
                {projection.awayTeam}
              </p>
              <p className="mt-1 text-3xl font-semibold">
                {projection.model.projectedScore.away.toFixed(1)}
              </p>
            </div>
            <span className="text-zinc-600 text-xl">@</span>
            <div className="text-center">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600">
                {projection.homeTeam}
              </p>
              <p className="mt-1 text-3xl font-semibold">
                {projection.model.projectedScore.home.toFixed(1)}
              </p>
            </div>
          </div>

          {/* Market lines */}
          <div className="mt-6 grid gap-3 sm:grid-cols-3">
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Spread</p>
              <p className="mt-2 text-lg font-semibold">
                {formatHomeSpreadLabel(projection.homeTeam, projection.market.homeSpread)}
              </p>
              <p className="mt-1 text-xs text-zinc-600">Current market spread</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Total</p>
              <p className="mt-2 text-lg font-semibold">
                {projection.market.total ?? "Unavailable"}
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Model Edge</p>
              <p className="mt-2 text-lg font-semibold">
                {projection.spreadAnalysis.edgePoints > 0 ? "+" : ""}
                {projection.spreadAnalysis.edgePoints.toFixed(1)} pts
              </p>
            </div>
          </div>
        </section>

        {/* SIA GAME INTELLIGENCE SUMMARY */}
        <section className="rounded-[32px] border border-white/[0.08] bg-[#0B1119] p-8">
          <p className="text-[11px] uppercase tracking-[0.2em] text-zinc-600">SIA Game Intelligence</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Matchup</p>
              <p className="mt-2 text-base font-semibold text-white">{projection.awayTeam} @ {projection.homeTeam}</p>
              <p className="mt-1 text-xs text-zinc-500">{formatKickoff(projection.commenceTime)}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Current Lean</p>
              <p className="mt-2 text-base font-semibold text-white">{intelligenceReport?.currentLean ?? "NO LEAN"}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Bet Status</p>
              <p className="mt-2 text-base font-semibold text-white">{intelligenceReport?.betStatus ?? (opportunity ? "QUALIFIED" : "NO QUALIFIED BET")}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">SI Score</p>
              <p className={`mt-2 text-2xl font-semibold ${scoreTone(si?.score)}`}>{si?.score?.toFixed(1) ?? "Pending"}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Confidence</p>
              <p className="mt-2 text-2xl font-semibold text-white">{intelligenceReport?.confidence != null ? `${intelligenceReport.confidence}%` : (opportunity ? `${opportunity.confidence}%` : "Pending")}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Current Market</p>
              <p className="mt-2 text-base font-semibold text-white">
                {formatHomeSpreadLabel(projection.homeTeam, projection.market.homeSpread)} · O/U {projection.market.total?.toFixed(1) ?? "—"}
              </p>
            </div>
          </div>
          <div className="mt-4 rounded-2xl border border-white/10 bg-white/[0.03] p-5">
            <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Why SIA Sees It This Way</p>
            <p className="mt-2 text-sm leading-6 text-zinc-400">
              {intelligenceReport?.whySummary ?? "SIA is awaiting enough model and market context to publish a complete intelligence summary for this game."}
            </p>
          </div>
        </section>

        {/* SIA INTELLIGENCE */}
        <section className="rounded-[32px] border border-white/[0.08] bg-[#0B1119] p-8">
          <p className="text-[11px] uppercase tracking-[0.2em] text-zinc-600">SIA Intelligence</p>

          {opportunity ? (
            <>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                  <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600 inline-flex items-center">SI Score<Tooltip term="SI Score" /></p>
                  <p className={`mt-2 text-2xl font-semibold ${scoreTone(si?.score)}`}>
                    {si?.score?.toFixed(1) ?? "—"}
                  </p>
                  <p className="mt-1 text-xs text-zinc-600">{si?.grade ?? ""}</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                  <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600 inline-flex items-center">Model Edge<Tooltip term="Model Edge" /></p>
                  <p className="mt-2 text-2xl font-semibold text-emerald-400">
                    +{opportunity.edge.toFixed(1)}%
                  </p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                  <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600 inline-flex items-center">EV / $1<Tooltip term="EV" /></p>
                  <p className="mt-2 text-2xl font-semibold text-emerald-400">
                    +${opportunity.evPerDollar.toFixed(3)}
                  </p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                  <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600 inline-flex items-center">Confidence<Tooltip term="Confidence" /></p>
                  <p className="mt-2 text-2xl font-semibold">{opportunity.confidence}%</p>
                </div>
              </div>

              <div className="mt-4 rounded-2xl border border-white/10 bg-white/[0.03] p-5">
                <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Recommended Bet</p>
                <p className="mt-2 text-xl font-semibold text-white">{opportunity.pick}</p>
                <p className="mt-1 text-sm text-zinc-400">
                  {opportunity.book} · {signedOdds(opportunity.price)} ·{" "}
                  {opportunity.recommendation}
                </p>
                <div className="mt-3 grid gap-3 sm:grid-cols-3 text-xs text-zinc-500">
                  <span>Model prob: {opportunity.modelProbability.toFixed(1)}%</span>
                  <span>Implied: {opportunity.impliedProbability.toFixed(1)}%</span>
                  <span>Kelly 20%: {(opportunity.kelly20 * 100).toFixed(1)}%</span>
                </div>
              </div>

              {/* Market Intelligence */}
              {mi && (
                <div className="mt-4 rounded-2xl border border-white/10 bg-white/[0.03] p-5">
                  <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600 inline-flex items-center">Market Intelligence<Tooltip term="Market Intelligence" /></p>
                  <p className="mt-2 text-base font-semibold">{mi.signal}</p>
                  <div className="mt-3 grid gap-3 sm:grid-cols-4 text-xs text-zinc-500">
                    <span>Score: {mi.score.toFixed(1)}/10</span>
                    <span>Books moving: {mi.booksMoving}/{mi.booksTracked}</span>
                    <span>Steam books: {mi.steamBooks}</span>
                    <span>Consensus: {mi.consensus.toFixed(0)}%</span>
                  </div>
                </div>
              )}

              {/* Actions */}
              <div className="mt-6 flex flex-wrap gap-3">
                <Button
                  onClick={() => void handleAddToCard()}
                  disabled={added}
                  className={added
                    ? "h-11 bg-emerald-400/10 px-6 text-emerald-300"
                    : "h-11 bg-white px-6 text-black hover:bg-zinc-200"}
                >
                  {added ? "Added to My Card ✓" : "Add to My Card"}
                </Button>
                <Link href={`/opportunities/${opportunity.id}`}>
                  <Button variant="outline" className="h-11 border-white/10 bg-transparent px-6 text-white hover:bg-white/[0.05]">
                    Full Opportunity Analysis →
                  </Button>
                </Link>
              </div>
              {snapshotError && (
                <p className="mt-2 text-xs text-amber-400">{snapshotError}</p>
              )}
            </>
          ) : (
            <div className="mt-4 space-y-3">
              <div className="rounded-2xl border border-dashed border-white/[0.08] p-6 text-sm text-zinc-500">
                {intelligenceReport?.betStatus === "INSUFFICIENT DATA"
                  ? "Insufficient data to publish a qualified bet recommendation."
                  : "No qualified SIA bet at current prices."}
              </div>
              {topNoBetReasons.length > 0 && (
                <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-5">
                  <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Why No Qualified Bet</p>
                  <ul className="mt-2 space-y-1 text-sm text-zinc-400">
                    {topNoBetReasons.map((reason) => (
                      <li key={reason}>• {reason}</li>
                    ))}
                  </ul>
                </div>
              )}
              <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-5">
                <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Bet Trigger</p>
                <p className="mt-2 text-sm text-zinc-400">{intelligenceReport?.betTrigger?.message ?? "Actionable price not currently available"}</p>
              </div>
            </div>
          )}
        </section>

        {/* MARKET ANALYSIS */}
        <section className="rounded-[32px] border border-white/[0.08] bg-[#0B1119] p-8">
          <p className="text-[11px] uppercase tracking-[0.2em] text-zinc-600">Market Analysis</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-3 text-sm">
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Spread</p>
              <p className="mt-2 font-semibold text-white">{formatHomeSpreadLabel(projection.homeTeam, projection.market.homeSpread)}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Total</p>
              <p className="mt-2 font-semibold text-white">{projection.market.total?.toFixed(1) ?? "Unavailable"}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Line Movement</p>
              <p className="mt-2 font-semibold text-white">Pending</p>
              <p className="mt-1 text-xs text-zinc-600">Actionable line-movement trigger is not currently available for this game.</p>
            </div>
          </div>
        </section>

        {/* MODEL PROJECTION */}
        <section className="rounded-[32px] border border-white/[0.08] bg-[#0B1119] p-8">
          <p className="text-[11px] uppercase tracking-[0.2em] text-zinc-600">Model Projection</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Away Power</p>
              <p className="mt-2 text-xl font-semibold">{projection.teamPower.away}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Home Power</p>
              <p className="mt-2 text-xl font-semibold">{projection.teamPower.home}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Home Cover Prob.</p>
              <p className="mt-2 text-xl font-semibold">
                {projection.spreadAnalysis.homeCoverProbability.toFixed(1)}%
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Fair Home Odds</p>
              <p className="mt-2 text-xl font-semibold">
                {projection.spreadAnalysis.homeCoverFairOdds}
              </p>
            </div>
          </div>
        </section>

        {/* CONTEXT */}
        <section className="rounded-[32px] border border-white/[0.08] bg-[#0B1119] p-8">
          <p className="text-[11px] uppercase tracking-[0.2em] text-zinc-600">Game Context</p>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            {/* Schedule / Rest */}
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Rest & Travel</p>
              {hasContext ? (
                <div className="mt-2 space-y-1 text-sm text-zinc-400">
                  <p>{restLabel}</p>
                  {context?.rest?.shortRestHome === true && <p className="text-amber-400">⚠ Short rest — home</p>}
                  {context?.rest?.shortRestAway === true && <p className="text-amber-400">⚠ Short rest — away</p>}
                  {travelMiles && (
                    <p>Travel: {travelMiles}</p>
                  )}
                  {travelShift && (
                    <p>Time zone shift: {travelShift}</p>
                  )}
                </div>
              ) : (
                <p className="mt-2 text-sm text-zinc-600">{context?.reason ?? "Unavailable"}</p>
              )}
            </div>

            {/* Injury */}
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Injury Context</p>
              {injury ? (
                <div className="mt-2 space-y-1 text-sm text-zinc-400">
                  {injury.awayInjuryScore != null && (
                    <p>Away injury score: {injury.awayInjuryScore.toFixed(1)}</p>
                  )}
                  {injury.homeInjuryScore != null && (
                    <p>Home injury score: {injury.homeInjuryScore.toFixed(1)}</p>
                  )}
                  <p className="text-xs text-zinc-600">
                    {injuryFreshness?.isLive ? "LIVE" : "CACHED"} · ESPN
                  </p>
                </div>
              ) : (
                <p className="mt-2 text-sm text-zinc-600">Unavailable</p>
              )}
            </div>

            {/* Weather */}
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Weather</p>
              {weather ? (
                <div className="mt-2 text-sm text-zinc-400">
                  <p>{weather.dataStatus ?? "UNAVAILABLE"}</p>
                  {weather.lastUpdated && (
                    <p className="mt-1 text-xs text-zinc-600">
                      Updated {new Date(weather.lastUpdated).toLocaleString()}
                    </p>
                  )}
                </div>
              ) : (
                <p className="mt-2 text-sm text-zinc-600">Unavailable</p>
              )}
            </div>
          </div>
        </section>

        {/* KEY MATCHUP FACTORS */}
        <section className="rounded-[32px] border border-white/[0.08] bg-[#0B1119] p-8">
          <p className="text-[11px] uppercase tracking-[0.2em] text-zinc-600">Key Matchup Factors</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 text-sm text-zinc-400">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Rest / Travel</p>
              <p className="mt-2">{hasContext ? restLabel : "Pending"}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 text-sm text-zinc-400">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Injury Intelligence</p>
              <p className="mt-2">{injury?.summary ?? "Pending"}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 text-sm text-zinc-400">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Weather</p>
              <p className="mt-2">{weather?.dataStatus ?? "Pending"}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 text-sm text-zinc-400">
              <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Social Intelligence</p>
              <p className="mt-2">{social?.summary ?? social?.reason ?? "Pending"}</p>
            </div>
          </div>
        </section>

        {/* SOCIAL INTELLIGENCE */}
        <section className="rounded-[32px] border border-white/[0.08] bg-[#0B1119] p-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-[11px] uppercase tracking-[0.2em] text-zinc-600">Social Intelligence</p>
              <p className="mt-2 max-w-3xl text-sm text-zinc-500">
                {social?.summary ?? social?.reason ?? "No social intelligence is currently attached to this matchup."}
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Badge variant="outline" className="border-amber-400/20 bg-amber-400/[0.08] text-amber-300">
                {social?.dataStatus ?? "MOCK"}
              </Badge>
              <Badge variant="outline" className="border-white/10 bg-white/[0.03] text-zinc-400">
                {social?.provider ?? "MOCK"}
              </Badge>
            </div>
          </div>

          {social?.available !== false && topSocialSignals.length > 0 ? (
            <>
              <div className="mt-5 grid gap-3 sm:grid-cols-3 text-xs text-zinc-500">
                <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                  <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Signals</p>
                  <p className="mt-2 text-xl font-semibold text-white">{social?.signalsDetected ?? topSocialSignals.length}</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                  <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Corroborated</p>
                  <p className="mt-2 text-xl font-semibold text-sky-300">{social?.corroboratedSignals ?? 0}</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                  <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">Confidence</p>
                  <p className="mt-2 text-xl font-semibold text-white">{social?.confidence?.toFixed(0) ?? "0"}/100</p>
                </div>
              </div>

              <div className="mt-5 space-y-3">
                {topSocialSignals.map((signal) => (
                  <article key={signal.signalId} className="rounded-2xl border border-white/10 bg-white/[0.03] p-5">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="text-[10px] uppercase tracking-[0.22em] text-zinc-600">
                          {signal.team} · {signal.category.replaceAll("_", " ")}
                        </p>
                        <p className="mt-2 text-base font-semibold text-white">
                          {signal.player ? `${signal.player}${signal.position ? ` (${signal.position})` : ""}` : "Team-level signal"}
                        </p>
                      </div>

                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <Badge variant="outline" className="border-white/10 bg-black/20 text-zinc-300">{signal.status}</Badge>
                        <Badge variant="outline" className="border-white/10 bg-black/20 text-zinc-400">Confidence {signal.confidence.toFixed(0)}</Badge>
                      </div>
                    </div>

                    <p className="mt-3 text-sm leading-6 text-zinc-400">{signal.textSummary}</p>

                    <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-xs text-zinc-500">
                      <span>Source: {signal.sourceName}</span>
                      <span>Credibility: {signal.sourceCredibility}/100</span>
                      <span>Impact: {signal.estimatedPointImpact.toFixed(2)} pts</span>
                      <span>Corroboration: {signal.corroborationCount}</span>
                    </div>
                  </article>
                ))}
              </div>

              <p className="mt-4 text-xs text-zinc-600">
                Mock-only Phase 1 social signals are shown for architecture validation and do not change recommendations or SI Score yet.
              </p>
            </>
          ) : (
            <div className="mt-5 rounded-2xl border border-dashed border-white/[0.08] p-6 text-sm text-zinc-500">
              {social?.reason ?? "No social signals detected for this matchup."}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
