"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import TeamLogo from "@/components/team-logo";
import { fetchJson } from "../lib/api";

type GameCard = {
  eventId: string;
  season: number;
  week: number;
  date: string;
  kickoff: string;
  awayTeam: string;
  homeTeam: string;
  awayLogo?: string;
  homeLogo?: string;
  marketSpread: number;
  marketTotal: number;
  projectedAwayScore: number;
  projectedHomeScore: number;
  sportsIntelligenceScore: number;
  marketGrade: string;
  bestBet: string;
  confidence: number;
  weatherSummary: string;
  injurySummary: string;
  lineMovementSummary: string;
};

type GamesResponse = {
  count: number;
  week?: number;
  date?: string;
  games: GameCard[];
};

const weekOptions = [1, 2, 3];
const dayOptions = ["Thu", "Fri", "Sat", "Sun", "Mon"];

function scoreTone(score: number) {
  if (score >= 85) return "text-emerald-400";
  if (score >= 75) return "text-sky-400";
  return "text-amber-400";
}

function recommendationBadge(grade: string) {
  if (grade === "Elite Opportunity") return "border-emerald-400/20 bg-emerald-400/[0.06] text-emerald-300";
  if (grade === "Lean") return "border-sky-400/20 bg-sky-400/[0.06] text-sky-300";
  return "border-amber-400/20 bg-amber-400/[0.06] text-amber-300";
}

export default function GamesPage() {
  const [games, setGames] = useState<GameCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [week, setWeek] = useState(1);
  const [day, setDay] = useState("All");

  useEffect(() => {
    async function loadGames() {
      try {
        setLoading(true);
        setError("");
        const query = new URLSearchParams();
        query.set("week", String(week));
        if (day !== "All") query.set("date", day);

        const data = await fetchJson<GamesResponse>(`/api/games?${query.toString()}`);
        setGames(data.games ?? []);
      } catch (err) {
        console.error(err);
        setError("Unable to load the full NFL slate right now.");
      } finally {
        setLoading(false);
      }
    }

    loadGames();
  }, [day, week]);

  const summaryLabel = useMemo(() => {
    if (games.length === 0) return "No games available";
    return `${games.length} games in focus`;
  }, [games.length]);

  return (
    <main className="min-h-screen bg-[#05070B] text-white">
      <div className="mx-auto flex max-w-7xl flex-col gap-8 px-6 py-8 lg:px-10">
        <header className="rounded-[32px] border border-white/10 bg-gradient-to-br from-white/[0.08] via-white/[0.04] to-transparent p-8 shadow-2xl shadow-black/30">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-[11px] uppercase tracking-[0.32em] text-zinc-500">Game Intelligence Hub</p>
              <h1 className="mt-3 text-4xl font-semibold tracking-tight">NFL Game Intelligence</h1>
              <p className="mt-3 max-w-3xl text-sm leading-7 text-zinc-400">
                Every scheduled game is presented as a premium intelligence card, layered with projection, market context, weather, injury, and line movement.
              </p>
            </div>
            <Badge variant="outline" className="border-white/10 bg-black/20 text-zinc-200">
              {summaryLabel}
            </Badge>
          </div>

          <div className="mt-8 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap gap-2">
              {weekOptions.map((weekOption) => (
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
                onClick={() => setDay("All")}
                className={`rounded-full border px-3 py-2 text-sm transition ${day === "All" ? "border-white/20 bg-white/[0.1] text-white" : "border-white/10 bg-transparent text-zinc-400 hover:text-white"}`}
              >
                All Days
              </button>
              {dayOptions.map((dayOption) => (
                <button
                  key={dayOption}
                  onClick={() => setDay(dayOption)}
                  className={`rounded-full border px-3 py-2 text-sm transition ${day === dayOption ? "border-white/20 bg-white/[0.1] text-white" : "border-white/10 bg-transparent text-zinc-400 hover:text-white"}`}
                >
                  {dayOption}
                </button>
              ))}
            </div>
          </div>
        </header>

        {error ? (
          <div className="rounded-[24px] border border-white/10 bg-[#0B1119] p-6 text-sm text-zinc-400">{error}</div>
        ) : null}

        {loading ? (
          <div className="rounded-[24px] border border-white/10 bg-[#0B1119] p-10 text-center text-sm text-zinc-400">
            Loading the full slate...
          </div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {games.map((game) => (
              <article key={game.eventId} className="rounded-[28px] border border-white/10 bg-[#0B1119] p-6 shadow-2xl shadow-black/20">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-[10px] uppercase tracking-[0.26em] text-zinc-600">{game.date}</p>
                    <p className="mt-2 text-sm text-zinc-400">{game.kickoff}</p>
                  </div>
                  <Badge variant="outline" className={recommendationBadge(game.marketGrade)}>
                    {game.marketGrade}
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
                    <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">Projected</p>
                    <p className="mt-2 text-xl font-semibold text-white">{game.projectedAwayScore} • {game.projectedHomeScore}</p>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                    <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">Spread / Total</p>
                    <p className="mt-2 text-xl font-semibold text-white">{game.marketSpread > 0 ? `+${game.marketSpread}` : game.marketSpread} / {game.marketTotal}</p>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                    <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">SI Score</p>
                    <p className={`mt-2 text-xl font-semibold ${scoreTone(game.sportsIntelligenceScore)}`}>{game.sportsIntelligenceScore}</p>
                  </div>
                </div>

                <div className="mt-6 rounded-[24px] border border-white/10 bg-black/20 p-5">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">Recommendation</p>
                      <p className="mt-2 text-lg font-semibold text-white">{game.bestBet}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">Confidence</p>
                      <p className="mt-2 text-lg font-semibold text-white">{game.confidence}%</p>
                    </div>
                  </div>

                  <div className="mt-4 rounded-2xl border border-white/10 bg-white/[0.03] p-4 text-sm leading-7 text-zinc-400">
                    <p><span className="font-medium text-zinc-200">Weather:</span> {game.weatherSummary}</p>
                    <p className="mt-2"><span className="font-medium text-zinc-200">Injury:</span> {game.injurySummary}</p>
                    <p className="mt-2"><span className="font-medium text-zinc-200">Line movement:</span> {game.lineMovementSummary}</p>
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
        )}
      </div>
    </main>
  );
}
