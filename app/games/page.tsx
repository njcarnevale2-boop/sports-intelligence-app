"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import TeamLogo from "@/components/team-logo";
import { fetchJson } from "../lib/api";

const GAMES_REQUEST_TIMEOUT_MS = 30000;

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
  moneyline?: { home?: number; away?: number } | null;
  bestOpportunity?: string | null;
  sportsIntelligenceScore?: number | null;
  marketIntelligence?: { grade?: string; signal?: string; booksTracked?: number } | null;
  bestAvailableLine?: {
    awaySpread?: { sportsbook?: string; line?: number | null; price?: number | null } | null;
    homeSpread?: { sportsbook?: string; line?: number | null; price?: number | null } | null;
    over?: { sportsbook?: string; line?: number | null; price?: number | null } | null;
    under?: { sportsbook?: string; line?: number | null; price?: number | null } | null;
  } | null;
  bestSportsbook?: {
    awaySpread?: string | null;
    homeSpread?: string | null;
    over?: string | null;
    under?: string | null;
  } | null;
  booksTracked?: number;
  marketLastUpdated?: string | null;
  marketProvider?: string;
  marketDataStatus?: string;
  injuryContext?: unknown | null;
  weatherContext?: unknown | null;
};

type GamesResponse = {
  count: number;
  week?: number;
  date?: string;
  source?: string;
  availableWeeks: number[];
  availableDates: string[];
  dataStatus?: {
    schedule?: string;
    opportunities?: string;
    marketIntelligence?: string;
    injury?: string;
    weather?: string;
  };
  games: GameCard[];
};

function scoreTone(score?: number | null) {
  if (score == null) return "text-zinc-400";
  if (score >= 85) return "text-emerald-400";
  if (score >= 75) return "text-sky-400";
  return "text-amber-400";
}

function recommendationBadge(grade?: string | null) {
  if (grade === "Elite Opportunity") return "border-emerald-400/20 bg-emerald-400/[0.06] text-emerald-300";
  if (grade === "Lean") return "border-sky-400/20 bg-sky-400/[0.06] text-sky-300";
  return "border-amber-400/20 bg-amber-400/[0.06] text-amber-300";
}

function formatKickoff(commenceTime: string) {
  const kickoff = new Date(commenceTime);
  if (Number.isNaN(kickoff.getTime())) return "Unavailable";
  return kickoff.toLocaleString("en-US", {
    weekday: "short",
    month: "short",
    day: "2-digit",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

function formatDateHeading(gameDate: string) {
  const date = new Date(`${gameDate}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return gameDate;
  return date.toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });
}

export default function GamesPage() {
  const [games, setGames] = useState<GameCard[]>([]);
  const [availableWeeks, setAvailableWeeks] = useState<number[]>([]);
  const [availableDates, setAvailableDates] = useState<string[]>([]);
  const [dataStatus, setDataStatus] = useState<GamesResponse["dataStatus"] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [week, setWeek] = useState<number | null>(null);
  const [selectedDate, setSelectedDate] = useState<string>("All");

  useEffect(() => {
    async function loadGames() {
      try {
        setLoading(true);
        setError("");
        const query = new URLSearchParams();
        if (week !== null) query.set("week", String(week));
        if (selectedDate !== "All") query.set("date", selectedDate);

        const data = await fetchJson<GamesResponse>(
          `/api/games?${query.toString()}`,
          undefined,
          GAMES_REQUEST_TIMEOUT_MS
        );
        setGames(data.games ?? []);
        setAvailableWeeks(data.availableWeeks ?? []);
        setAvailableDates(data.availableDates ?? []);
        setDataStatus(data.dataStatus ?? null);

        if (week === null && data.availableWeeks?.length) {
          setWeek(data.availableWeeks[0]);
        }

        if (selectedDate !== "All" && data.availableDates && !data.availableDates.includes(selectedDate)) {
          setSelectedDate("All");
        }
      } catch (err) {
        console.error(err);
        if (err instanceof Error && err.message === "Request timed out") {
          setError("Game data is taking longer than expected. Please try again.");
        } else {
          setError("Unable to load the full NFL slate right now.");
        }
      } finally {
        setLoading(false);
      }
    }

    loadGames();
  }, [selectedDate, week]);

  const summaryLabel = useMemo(() => {
    if (games.length === 0) return "No games available";
    return `${games.length} games in slate`;
  }, [games.length]);

  const groupedGames = useMemo(() => {
    const grouped = new Map<string, GameCard[]>();
    for (const game of games) {
      const key = game.gameDate;
      const existing = grouped.get(key) ?? [];
      existing.push(game);
      grouped.set(key, existing);
    }
    return Array.from(grouped.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [games]);

  const statusLabel = useMemo(() => {
    if (!dataStatus) return "UNAVAILABLE";
    return [
      `Schedule ${dataStatus.schedule ?? "UNAVAILABLE"}`,
      `Market ${dataStatus.marketIntelligence ?? "UNAVAILABLE"}`,
      `Injury ${dataStatus.injury ?? "UNAVAILABLE"}`,
      `Weather ${dataStatus.weather ?? "UNAVAILABLE"}`,
    ].join(" • ");
  }, [dataStatus]);

  return (
    <main className="min-h-screen bg-[#05070B] text-white">
      <div className="mx-auto flex max-w-7xl flex-col gap-8 px-6 py-8 lg:px-10">
        <header className="rounded-[32px] border border-white/10 bg-gradient-to-br from-white/[0.08] via-white/[0.04] to-transparent p-8 shadow-2xl shadow-black/30">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-[11px] uppercase tracking-[0.32em] text-zinc-500">Game Intelligence Hub</p>
              <h1 className="mt-3 text-4xl font-semibold tracking-tight">NFL Game Intelligence</h1>
              <p className="mt-3 max-w-3xl text-sm leading-7 text-zinc-400">
                Complete NFL schedule coverage by week and date, with optional intelligence overlays when available.
              </p>
            </div>
            <Badge variant="outline" className="border-white/10 bg-black/20 text-zinc-200">
              {summaryLabel}
            </Badge>
          </div>

          <div className="mt-8 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap gap-2">
              {availableWeeks.map((weekOption) => (
                <button
                  key={weekOption}
                  onClick={() => setWeek(weekOption)}
                  className={`rounded-full border px-4 py-2 text-sm transition ${week === weekOption ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-300" : "border-white/10 bg-white/[0.04] text-zinc-300 hover:bg-white/[0.08]"}`}
                >
                  Week {weekOption}
                </button>
              ))}
            </div>

            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => setSelectedDate("All")}
                className={`rounded-full border px-3 py-2 text-sm transition ${selectedDate === "All" ? "border-white/20 bg-white/[0.1] text-white" : "border-white/10 bg-transparent text-zinc-400 hover:text-white"}`}
              >
                All Dates
              </button>
              {availableDates.map((dateOption) => (
                <button
                  key={dateOption}
                  onClick={() => setSelectedDate(dateOption)}
                  className={`rounded-full border px-3 py-2 text-sm transition ${selectedDate === dateOption ? "border-white/20 bg-white/[0.1] text-white" : "border-white/10 bg-transparent text-zinc-400 hover:text-white"}`}
                >
                  {dateOption}
                </button>
              ))}
            </div>
          </div>

          <p className="mt-6 text-xs uppercase tracking-[0.18em] text-zinc-500">{statusLabel}</p>
        </header>

        {error ? (
          <div className="rounded-[24px] border border-white/10 bg-[#0B1119] p-6 text-sm text-zinc-400">{error}</div>
        ) : null}

        {loading ? (
          <div className="rounded-[24px] border border-white/10 bg-[#0B1119] p-10 text-center text-sm text-zinc-400">
            Loading complete NFL slate...
          </div>
        ) : (
          <div className="space-y-8">
            {groupedGames.map(([date, items]) => (
              <section key={date}>
                <h2 className="mb-4 text-lg font-semibold text-zinc-200">{formatDateHeading(date)}</h2>
                <div className="grid gap-4 xl:grid-cols-2">
                  {items.map((game) => (
                    <article key={game.eventId} className="rounded-[28px] border border-white/10 bg-[#0B1119] p-6 shadow-2xl shadow-black/20">
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <p className="text-[10px] uppercase tracking-[0.26em] text-zinc-600">{game.gameDate}</p>
                          <p className="mt-2 text-sm text-zinc-400">{formatKickoff(game.commenceTime)}</p>
                        </div>
                        <Badge variant="outline" className={recommendationBadge(game.bestOpportunity || undefined)}>
                          {game.status}
                        </Badge>
                      </div>

                      <div className="mt-6 flex items-center justify-between gap-4">
                        <div className="flex flex-1 items-center gap-3">
                          <TeamLogo src={game.awayLogo} alt={game.awayTeam} size={56} />
                          <div>
                            <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-500">Away</p>
                            <p className="text-lg font-semibold">{game.awayTeam}</p>
                          </div>
                        </div>

                        <div className="px-3 text-center text-sm font-medium text-zinc-500">@</div>

                        <div className="flex flex-1 items-center justify-end gap-3">
                          <div className="text-right">
                            <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-500">Home</p>
                            <p className="text-lg font-semibold">{game.homeTeam}</p>
                          </div>
                          <TeamLogo src={game.homeLogo} alt={game.homeTeam} size={56} />
                        </div>
                      </div>

                      <div className="mt-6 grid gap-3 md:grid-cols-3">
                        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                          <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">Spread / Total</p>
                          <p className="mt-2 text-xl font-semibold text-white">
                            {game.spread == null ? "Unavailable" : game.spread > 0 ? `+${game.spread}` : game.spread} / {game.total ?? "Unavailable"}
                          </p>
                        </div>
                        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                          <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">Moneyline</p>
                          <p className="mt-2 text-xl font-semibold text-white">
                            {game.moneyline ? `H ${game.moneyline.home ?? "N/A"} • A ${game.moneyline.away ?? "N/A"}` : "Unavailable"}
                          </p>
                        </div>
                        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                          <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">SI Score</p>
                          <p className={`mt-2 text-xl font-semibold ${scoreTone(game.sportsIntelligenceScore)}`}>
                            {game.sportsIntelligenceScore ?? "Unavailable"}
                          </p>
                        </div>
                      </div>

                      <div className="mt-6 rounded-[24px] border border-white/10 bg-black/20 p-5">
                        <div className="space-y-2 text-sm leading-7 text-zinc-400">
                          <p><span className="font-medium text-zinc-200">Best opportunity:</span> {game.bestOpportunity ?? "Unavailable"}</p>
                          <p><span className="font-medium text-zinc-200">Market signal:</span> {game.marketIntelligence?.signal ?? "Unavailable"}</p>
                          <p><span className="font-medium text-zinc-200">Best sportsbook:</span> {game.bestSportsbook?.homeSpread ?? game.bestSportsbook?.awaySpread ?? "Unavailable"}</p>
                          <p><span className="font-medium text-zinc-200">Best spread line:</span> {game.bestAvailableLine?.homeSpread ? `${game.bestAvailableLine.homeSpread.line ?? "N/A"} (${game.bestAvailableLine.homeSpread.price ?? "N/A"})` : "Unavailable"}</p>
                          <p><span className="font-medium text-zinc-200">Books tracked:</span> {game.booksTracked ?? 0}</p>
                          <p><span className="font-medium text-zinc-200">Market last updated:</span> {game.marketLastUpdated ? new Date(game.marketLastUpdated).toLocaleString() : "Unavailable"}</p>
                          <p><span className="font-medium text-zinc-200">Market source:</span> {game.marketProvider ?? "Unavailable"} ({game.marketDataStatus ?? "UNAVAILABLE"})</p>
                          <p><span className="font-medium text-zinc-200">Injury context:</span> Unavailable</p>
                          <p><span className="font-medium text-zinc-200">Weather context:</span> Unavailable</p>
                        </div>
                      </div>

                      <div className="mt-6 flex flex-wrap gap-3">
                        <Link href={`/opportunities/${game.eventId}`} className="rounded-full border border-white/10 px-4 py-2 text-sm text-zinc-300 transition hover:border-white/20 hover:text-white">
                          View Intelligence
                        </Link>
                        <Link href="/line-movement" className="rounded-full border border-white/10 px-4 py-2 text-sm text-zinc-300 transition hover:border-white/20 hover:text-white">
                          View Line Movement
                        </Link>
                        <Link href={`/opportunities?eventId=${game.eventId}`} className="rounded-full border border-white/10 px-4 py-2 text-sm text-zinc-300 transition hover:border-white/20 hover:text-white">
                          View Full Analysis
                        </Link>
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
