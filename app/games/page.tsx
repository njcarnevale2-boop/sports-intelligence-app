"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import TeamLogo from "@/components/team-logo";
import { fetchJson } from "../lib/api";
import { formatDateUtcHeading, formatDateUtcTab, formatKickoffDateEt, formatKickoffTimeEt } from "@/app/lib/time-format";

const GAMES_REQUEST_TIMEOUT_MS = 30000;

// ---------------------------------------------------------------------------
// Types — shape matches /api/games response, no backend changes needed
// ---------------------------------------------------------------------------

type GameCard = {
  eventId: string;
  season: number;
  week: number;
  gameDate: string;
  commenceTime: string;
  awayTeam: string;
  homeTeam: string;
  awayAbbreviation?: string | null;
  homeAbbreviation?: string | null;
  awayLogo?: string;
  homeLogo?: string;
  status: string;
  spread?: number | null;
  spreadSource?: string;
  total?: number | null;
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
  betStatus?: string | null;
  recommendation?: string | null;
  qualificationStatus?: string | null;
};

type GamesResponse = {
  count: number;
  availableWeeks: number[];
  availableDates: string[];
  dataStatus?: { marketIntelligence?: string };
  games: GameCard[];
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function scoreTone(score?: number | null) {
  if (score == null) return "text-zinc-500";
  if (score >= 85) return "text-emerald-400";
  if (score >= 75) return "text-sky-400";
  return "text-amber-400";
}

function signedSpread(spread: number) {
  return spread > 0 ? `+${spread}` : `${spread}`;
}

function formatTeamSpread(game: GameCard) {
  if (game.spread == null) return "—";
  const homeLabel = game.homeAbbreviation || game.homeTeam;
  return `${homeLabel} ${signedSpread(game.spread)}`;
}

function compactBetStatus(game: GameCard) {
  if (game.bestOpportunity) {
    const prefix = (game.betStatus || "BET").replace("QUALIFIED", "BET");
    const score = game.sportsIntelligenceScore != null ? ` · ${game.sportsIntelligenceScore.toFixed(1)}` : "";
    const price = game.bestOpportunityDetail?.price;
    const pricedPick = price != null ? `${game.bestOpportunity} (${price > 0 ? `+${price}` : `${price}`})` : game.bestOpportunity;
    return `${prefix} · ${pricedPick}${score}`;
  }
  if ((game.betStatus || "").toUpperCase().includes("INSUFFICIENT")) return "PASS · Insufficient data";
  return "PASS · No meaningful edge";
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function GamesPage() {
  const [games, setGames] = useState<GameCard[]>([]);
  const [availableWeeks, setAvailableWeeks] = useState<number[]>([]);
  const [availableDates, setAvailableDates] = useState<string[]>([]);
  const [marketStatus, setMarketStatus] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [week, setWeek] = useState<number | null>(null);
  const [selectedDate, setSelectedDate] = useState<string>("All");

  // Initialize: fetch metadata and set initial week once on mount
  useEffect(() => {
    async function initializeMetadata() {
      try {
        const data = await fetchJson<GamesResponse>(
          `/api/games`,
          undefined,
          GAMES_REQUEST_TIMEOUT_MS
        );

        setAvailableWeeks(data.availableWeeks ?? []);
        setAvailableDates(data.availableDates ?? []);
        setMarketStatus(data.dataStatus?.marketIntelligence ?? null);

        if (data.availableWeeks?.length) {
          setWeek(data.availableWeeks[0]);
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : "";
        setError(
          msg === "Request timed out"
            ? "Game data is taking longer than expected — try again."
            : "Unable to load the NFL slate right now."
        );
      } finally {
        setLoading(false);
      }
    }

    void initializeMetadata();
  }, []); // Run only on mount

  // Fetch games when week/date changes
  useEffect(() => {
    async function load() {
      // Skip if week hasn't been initialized yet
      if (week === null) return;

      try {
        setLoading(true);
        setError("");

        const q = new URLSearchParams();
        q.set("week", String(week));
        if (selectedDate !== "All") q.set("date", selectedDate);

        const data = await fetchJson<GamesResponse>(
          `/api/games?${q.toString()}`,
          undefined,
          GAMES_REQUEST_TIMEOUT_MS
        );

        setGames(data.games ?? []);

        if (selectedDate !== "All" && data.availableDates && !data.availableDates.includes(selectedDate)) {
          setSelectedDate("All");
        }
      } catch (err) {
        const msg = err instanceof Error ? err.message : "";
        setError(
          msg === "Request timed out"
            ? "Game data is taking longer than expected — try again."
            : "Unable to load the NFL slate right now."
        );
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, [week, selectedDate]);

  function changeWeek(w: number) {
    setSelectedDate("All");
    setWeek(w);
  }

  const prevWeek =
    week !== null && availableWeeks.length > 0
      ? (availableWeeks[availableWeeks.indexOf(week) - 1] ?? null)
      : null;
  const nextWeek =
    week !== null && availableWeeks.length > 0
      ? (availableWeeks[availableWeeks.indexOf(week) + 1] ?? null)
      : null;

  const qualifiedCount = useMemo(
    () => games.filter((g) => g.bestOpportunity).length,
    [games]
  );

  const groupedGames = useMemo(() => {
    const map = new Map<string, GameCard[]>();
    for (const game of games) {
      map.set(game.gameDate, [...(map.get(game.gameDate) ?? []), game]);
    }
    return Array.from(map.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [games]);

  return (
    <main className="min-h-screen bg-[#05070B] text-white">
      <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6 lg:px-8">

        {/* HEADER */}
        <header className="mb-8">
          <p className="text-[11px] uppercase tracking-[0.28em] text-zinc-600">Sports Intelligence</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">NFL Games</h1>
          <p className="mt-2 text-sm text-zinc-500">
            Complete NFL slate with Sports Intelligence layered on top.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-3 text-xs">
            {week !== null && (
              <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-zinc-400">
                Week {week}
              </span>
            )}
            {!loading && (
              <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-zinc-400">
                {games.length} Games Analyzed
              </span>
            )}
            {!loading && qualifiedCount > 0 && (
              <span className="rounded-full border border-emerald-400/20 bg-emerald-400/[0.06] px-3 py-1 text-emerald-400">
                {qualifiedCount} Qualified {qualifiedCount === 1 ? "Opportunity" : "Opportunities"}
              </span>
            )}
            {marketStatus && marketStatus !== "UNAVAILABLE" && (
              <span className="text-zinc-700">Market {marketStatus}</span>
            )}
          </div>
        </header>

        {/* WEEK NAVIGATION */}
        <div className="mb-5 flex items-center gap-2">
          <button
            onClick={() => prevWeek !== null && changeWeek(prevWeek)}
            disabled={prevWeek === null}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] text-base text-zinc-400 transition hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-30"
            aria-label="Previous week"
          >
            ‹
          </button>

          <select
            value={week ?? ""}
            onChange={(e) => changeWeek(Number(e.target.value))}
            className="h-9 flex-1 rounded-lg border border-white/10 bg-[#0D131C] px-3 text-sm font-medium text-white outline-none sm:flex-none sm:w-36"
          >
            {availableWeeks.map((w) => (
              <option key={w} value={w}>Week {w}</option>
            ))}
          </select>

          <button
            onClick={() => nextWeek !== null && changeWeek(nextWeek)}
            disabled={nextWeek === null}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] text-base text-zinc-400 transition hover:bg-white/[0.08] disabled:cursor-not-allowed disabled:opacity-30"
            aria-label="Next week"
          >
            ›
          </button>
        </div>

        {/* DATE FILTER */}
        {availableDates.length > 1 && (
          <div className="mb-8 flex gap-2 overflow-x-auto pb-1">
            <button
              onClick={() => setSelectedDate("All")}
              className={`shrink-0 rounded-full border px-4 py-1.5 text-xs font-medium transition ${
                selectedDate === "All"
                  ? "border-white/20 bg-white/[0.1] text-white"
                  : "border-white/10 bg-transparent text-zinc-500 hover:text-white"
              }`}
            >
              ALL
            </button>
            {availableDates.map((d) => (
              <button
                key={d}
                onClick={() => setSelectedDate(d)}
                className={`shrink-0 rounded-full border px-4 py-1.5 text-xs font-medium transition ${
                  selectedDate === d
                    ? "border-white/20 bg-white/[0.1] text-white"
                    : "border-white/10 bg-transparent text-zinc-500 hover:text-white"
                }`}
              >
                {formatDateUtcTab(d)}
              </button>
            ))}
          </div>
        )}

        {/* LOADING / ERROR */}
        {error && (
          <p className="mb-6 rounded-xl border border-white/10 bg-[#0B1119] px-5 py-4 text-sm text-zinc-400">
            {error}
          </p>
        )}

        {loading && (
          <div className="py-16 text-center text-sm text-zinc-600">
            Loading Week {week ?? "…"}…
          </div>
        )}

        {/* GAME LIST */}
        {!loading && !error && (
          <div className="space-y-10">
            {groupedGames.length === 0 ? (
              <p className="py-12 text-center text-sm text-zinc-600">
                No games found for this selection.
              </p>
            ) : (
              groupedGames.map(([date, dayGames]) => (
                <section key={date}>
                  <h2 className="mb-3 text-[10px] font-semibold uppercase tracking-[0.22em] text-zinc-600">
                    {formatDateUtcHeading(date)}
                  </h2>
                  <div className="space-y-2">
                    {dayGames.map((game) => (
                      <GameRow key={game.eventId} game={game} />
                    ))}
                  </div>
                </section>
              ))
            )}
          </div>
        )}

      </div>
    </main>
  );
}

// ---------------------------------------------------------------------------
// Game row — scannable rigid layout, no overlap
// ---------------------------------------------------------------------------

function GameRow({ game }: { game: GameCard }) {
  const hasOpp = Boolean(game.bestOpportunity);
  const kickoffDate = formatKickoffDateEt(game.commenceTime);
  const kickoffTime = formatKickoffTimeEt(game.commenceTime);

  return (
    <>
      {/* Desktop layout: grid columns */}
      <article className="hidden sm:flex items-center gap-3 rounded-xl border border-white/[0.07] bg-[#0B1119] px-6 py-4 transition hover:border-white/[0.14] hover:bg-white/[0.02]">

        {/* MATCHUP (max 2 columns) */}
        <div className="flex items-center gap-4 min-w-max">
          <div className="flex items-center gap-2">
            <TeamLogo src={game.awayLogo} alt={game.awayTeam} size={32} />
            <span className="text-sm font-semibold text-white">{game.awayAbbreviation || game.awayTeam}</span>
          </div>
          <span className="text-xs text-zinc-600 mx-1">@</span>
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-white">{game.homeAbbreviation || game.homeTeam}</span>
            <TeamLogo src={game.homeLogo} alt={game.homeTeam} size={32} />
          </div>
        </div>

        {/* KICKOFF */}
        <div className="flex flex-col items-start min-w-[90px] flex-shrink-0">
          <span className="text-xs text-zinc-600">{kickoffDate}</span>
          <span className="text-xs font-medium text-zinc-300">{kickoffTime}</span>
        </div>

        {/* SPREAD */}
        <div className="flex flex-col items-start min-w-[70px] flex-shrink-0">
          <span className="text-[10px] text-zinc-600">{game.spreadSource === "CONSENSUS_AVERAGE" ? "CONSENSUS" : "SPREAD"}</span>
          <span className="text-sm font-semibold text-zinc-200 mt-0.5">
            {formatTeamSpread(game)}
          </span>
        </div>

        {/* TOTAL */}
        <div className="flex flex-col items-start min-w-[70px] flex-shrink-0">
          <span className="text-[10px] text-zinc-600">TOTAL</span>
          <span className="text-sm font-semibold text-zinc-200 mt-0.5">
            {game.total != null ? game.total.toFixed(1) : "—"}
          </span>
        </div>

        {/* SIA SIGNAL */}
        <div className="flex flex-col items-start min-w-[140px] flex-shrink-0 ml-auto">
          {hasOpp ? (
            <>
              <span className={`text-[11px] font-semibold ${scoreTone(game.sportsIntelligenceScore)}`}>
                {compactBetStatus(game)}
              </span>
            </>
          ) : (
            <span className="text-[11px] text-zinc-500">{compactBetStatus(game)}</span>
          )}
        </div>

        {/* ACTION */}
        <Link
          href={`/games/${game.eventId}`}
          className="shrink-0 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-zinc-400 transition hover:border-white/20 hover:bg-white/[0.08] hover:text-white ml-2"
        >
          View Intelligence →
        </Link>
      </article>

      {/* Mobile card layout */}
      <article className="sm:hidden rounded-xl border border-white/[0.07] bg-[#0B1119] p-4 transition hover:border-white/[0.14] hover:bg-white/[0.02]">
        {/* Matchup + logos */}
        <div className="flex items-center justify-center gap-3 mb-3">
          <div className="flex items-center gap-2">
            <TeamLogo src={game.awayLogo} alt={game.awayTeam} size={28} />
            <span className="text-sm font-semibold text-white">{game.awayAbbreviation || game.awayTeam}</span>
          </div>
          <span className="text-xs text-zinc-600">@</span>
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-white">{game.homeAbbreviation || game.homeTeam}</span>
            <TeamLogo src={game.homeLogo} alt={game.homeTeam} size={28} />
          </div>
        </div>

        {/* Kickoff */}
        <div className="text-center text-xs mb-3">
          <span className="text-zinc-600">{kickoffDate}</span>
          <span className="text-zinc-600 mx-1">•</span>
          <span className="font-medium text-zinc-300">{kickoffTime}</span>
        </div>

        {/* Spread + Total */}
        <div className="flex gap-4 justify-center mb-3 text-sm">
          <div className="flex flex-col items-center">
            <span className="text-[10px] text-zinc-600">{game.spreadSource === "CONSENSUS_AVERAGE" ? "CONSENSUS" : "SPREAD"}</span>
            <span className="font-semibold text-zinc-200 mt-0.5">
              {formatTeamSpread(game)}
            </span>
          </div>
          <div className="flex flex-col items-center">
            <span className="text-[10px] text-zinc-600">TOTAL</span>
            <span className="font-semibold text-zinc-200 mt-0.5">
              {game.total != null ? game.total.toFixed(1) : "—"}
            </span>
          </div>
        </div>

        {/* SIA Signal */}
        {hasOpp && (
          <div className="text-center mb-3 pb-3 border-b border-white/[0.05]">
            <div className={`text-[11px] font-semibold ${scoreTone(game.sportsIntelligenceScore)}`}>
              {compactBetStatus(game)}
            </div>
          </div>
        )}
        {!hasOpp && (
          <div className="text-center mb-3 pb-3 border-b border-white/[0.05]">
            <div className="text-[11px] text-zinc-500">{compactBetStatus(game)}</div>
          </div>
        )}

        {/* Action */}
        <Link
          href={`/games/${game.eventId}`}
          className="block text-center rounded-lg border border-white/10 bg-white/[0.04] px-3 py-2 text-xs font-medium text-zinc-400 transition hover:border-white/20 hover:bg-white/[0.08] hover:text-white"
        >
          View Intelligence →
        </Link>
      </article>
    </>
  );
}


