"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import TeamLogo from "@/components/team-logo";
import { fetchJson } from "../lib/api";

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
  total?: number | null;
  bestOpportunity?: string | null;
  sportsIntelligenceScore?: number | null;
  marketDataStatus?: string;
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

function formatKickoff(iso: string) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "TBD";
  return d.toLocaleString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

function formatDateHeading(dateStr: string) {
  const d = new Date(`${dateStr}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return dateStr;
  return d.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  }).toUpperCase();
}

function formatDateTab(dateStr: string) {
  const d = new Date(`${dateStr}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return dateStr;
  return d.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  }).toUpperCase();
}

function scoreTone(score?: number | null) {
  if (score == null) return "text-zinc-500";
  if (score >= 85) return "text-emerald-400";
  if (score >= 75) return "text-sky-400";
  return "text-amber-400";
}

function signedSpread(spread: number) {
  return spread > 0 ? `+${spread}` : `${spread}`;
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

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        setError("");

        const q = new URLSearchParams();
        if (week !== null) q.set("week", String(week));
        if (selectedDate !== "All") q.set("date", selectedDate);

        const data = await fetchJson<GamesResponse>(
          `/api/games?${q.toString()}`,
          undefined,
          GAMES_REQUEST_TIMEOUT_MS
        );

        setGames(data.games ?? []);
        setAvailableWeeks((prev) => {
          const next = data.availableWeeks ?? [];
          return next.length >= prev.length ? next : prev;
        });
        setAvailableDates(data.availableDates ?? []);
        setMarketStatus(data.dataStatus?.marketIntelligence ?? null);

        if (week === null && data.availableWeeks?.length) {
          setWeek(data.availableWeeks[0]);
        }
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
                {games.length} {games.length === 1 ? "game" : "games"}
              </span>
            )}
            {!loading && qualifiedCount > 0 && (
              <span className="rounded-full border border-emerald-400/20 bg-emerald-400/[0.06] px-3 py-1 text-emerald-400">
                {qualifiedCount} qualified {qualifiedCount === 1 ? "opportunity" : "opportunities"}
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
                {formatDateTab(d)}
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
                    {formatDateHeading(date)}
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
// Game row — scannable, week-first, minimal
// ---------------------------------------------------------------------------

function GameRow({ game }: { game: GameCard }) {
  const hasOpp = Boolean(game.bestOpportunity);

  return (
    <article className="group rounded-xl border border-white/[0.07] bg-[#0B1119] px-5 py-4 transition hover:border-white/[0.14] hover:bg-white/[0.02]">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">

        {/* Teams + kickoff */}
        <div className="flex flex-1 flex-col gap-3 sm:flex-row sm:items-center sm:gap-6">
          {/* Teams */}
          <div className="flex items-center gap-5 flex-1">
            <div className="flex items-center gap-2 min-w-0">
              <TeamLogo src={game.awayLogo} alt={game.awayTeam} size={36} />
              <span className="text-sm font-semibold leading-tight truncate">{game.awayTeam}</span>
            </div>
            <span className="shrink-0 text-xs text-zinc-600">@</span>
            <div className="flex items-center gap-2 min-w-0">
              <TeamLogo src={game.homeLogo} alt={game.homeTeam} size={36} />
              <span className="text-sm font-semibold leading-tight truncate">{game.homeTeam}</span>
            </div>
          </div>

          {/* Kickoff */}
          <p className="text-xs text-zinc-600 shrink-0">{formatKickoff(game.commenceTime)}</p>
        </div>

        {/* Right: lines + SI + action */}
        <div className="flex items-center justify-between gap-4 sm:justify-end sm:gap-6">
          {/* Spread / Total */}
          <div className="flex items-center gap-4 text-sm">
            {game.spread != null ? (
              <span>
                <span className="text-[10px] text-zinc-600 mr-1">Sprd</span>
                <span className="text-zinc-200">{signedSpread(game.spread)}</span>
              </span>
            ) : null}
            {game.total != null ? (
              <span>
                <span className="text-[10px] text-zinc-600 mr-1">O/U</span>
                <span className="text-zinc-200">{game.total}</span>
              </span>
            ) : null}
            {game.spread == null && game.total == null && (
              <span className="text-xs text-zinc-700">No lines</span>
            )}
          </div>

          {/* SI score + opportunity text */}
          <div className="hidden sm:flex flex-col items-end min-w-[140px]">
            {hasOpp ? (
              <>
                {game.sportsIntelligenceScore != null && (
                  <span className={`text-xs font-semibold ${scoreTone(game.sportsIntelligenceScore)}`}>
                    SI {game.sportsIntelligenceScore.toFixed(1)}
                  </span>
                )}
                <span className="mt-0.5 text-[11px] text-zinc-400 text-right leading-snug max-w-[150px]">
                  {game.bestOpportunity}
                </span>
              </>
            ) : (
              <span className="text-[11px] text-zinc-700">No opportunity</span>
            )}
          </div>

          {/* Action */}
          <Link
            href={`/games/${game.eventId}`}
            className="shrink-0 rounded-lg border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-zinc-400 transition hover:border-white/20 hover:bg-white/[0.08] hover:text-white"
          >
            View →
          </Link>
        </div>
      </div>

      {/* Mobile: SI + opportunity below teams */}
      {hasOpp && (
        <div className="mt-2 flex items-center gap-2 sm:hidden">
          {game.sportsIntelligenceScore != null && (
            <span className={`text-xs font-semibold ${scoreTone(game.sportsIntelligenceScore)}`}>
              SI {game.sportsIntelligenceScore.toFixed(1)}
            </span>
          )}
          <span className="text-[11px] text-zinc-500 leading-snug">
            {game.bestOpportunity}
          </span>
        </div>
      )}
    </article>
  );
}

