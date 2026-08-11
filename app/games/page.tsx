"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { fetchJson } from "../lib/api";

type SportsIntelligenceScore = {
  score: number;
  grade: string;
  stars: number;
  recommendation: string;
};

type MarketIntelligence = {
  score: number;
  grade: string;
  signal: string;
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
  edge: number;
  sportsIntelligenceScore: SportsIntelligenceScore;
  marketIntelligence: MarketIntelligence;
};

type OpportunitiesResponse = {
  count: number;
  source: string;
  opportunities: Opportunity[];
};

type GameCard = {
  eventId: string;
  matchup: string;
  commenceTime: string;
  opportunity?: Opportunity;
};

function formatDateTime(value: string) {
  if (!value) return "TBD";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;

  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export default function GamesPage() {
  const [games, setGames] = useState<GameCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadGames() {
      try {
        const data: OpportunitiesResponse = await fetchJson<OpportunitiesResponse>("/api/opportunities?limit=50");
        const grouped = new Map<string, Opportunity[]>();

        for (const opportunity of data.opportunities) {
          const bucket = grouped.get(opportunity.eventId) ?? [];
          bucket.push(opportunity);
          grouped.set(opportunity.eventId, bucket);
        }

        const cards = Array.from(grouped.entries())
          .map(([eventId, opportunities]) => {
            const best = [...opportunities].sort(
              (left, right) =>
                (right.sportsIntelligenceScore?.score ?? 0) -
                (left.sportsIntelligenceScore?.score ?? 0)
            )[0];

            return {
              eventId,
              matchup: best?.matchup ?? opportunities[0]?.matchup ?? "Upcoming matchup",
              commenceTime: best?.commenceTime ?? opportunities[0]?.commenceTime ?? "",
              opportunity: best,
            };
          })
          .sort((left, right) => left.commenceTime.localeCompare(right.commenceTime));

        setGames(cards);
      } catch (err) {
        console.error(err);
        setError("Unable to load game intelligence right now.");
      } finally {
        setLoading(false);
      }
    }

    loadGames();
  }, []);

  const summaryLabel = useMemo(() => {
    if (games.length === 0) return "No live matchup data yet";
    return `${games.length} upcoming games tracked`;
  }, [games.length]);

  if (loading) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:px-10">
          <p className="text-sm text-zinc-500">Pulling game intelligence...</p>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-6xl px-6 py-10 lg:px-10">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Game research</p>
            <h1 className="mt-3 text-4xl font-semibold tracking-tight">Games</h1>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-zinc-500">
              NFL game intelligence and matchup research built from the current opportunity board.
            </p>
          </div>

          <Badge variant="outline" className="border-white/10 bg-white/[0.04] text-zinc-300">
            {summaryLabel}
          </Badge>
        </div>

        {error ? (
          <div className="mt-8 rounded-3xl border border-white/10 bg-[#0B1119] p-8 text-sm text-zinc-400">
            {error}
          </div>
        ) : null}

        <div className="mt-10 grid gap-4 xl:grid-cols-2">
          {games.map((game) => (
            <article key={game.eventId} className="rounded-3xl border border-white/10 bg-[#0B1119] p-7 shadow-2xl shadow-black/25">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600">Matchup</p>
                  <h2 className="mt-2 text-2xl font-semibold tracking-tight">{game.matchup}</h2>
                  <p className="mt-2 text-sm text-zinc-500">{formatDateTime(game.commenceTime)}</p>
                </div>

                <Badge
                  variant="outline"
                  className={
                    game.opportunity
                      ? "border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-400"
                      : "border-white/10 bg-white/[0.04] text-zinc-300"
                  }
                >
                  {game.opportunity ? game.opportunity.sportsIntelligenceScore.recommendation : "No qualified opportunity"}
                </Badge>
              </div>

              {game.opportunity ? (
                <div className="mt-8 grid gap-4 md:grid-cols-2">
                  <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                    <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Best opportunity</p>
                    <p className="mt-3 text-lg font-semibold text-white">{game.opportunity.pick}</p>
                    <p className="mt-2 text-sm text-zinc-500">{game.opportunity.book} • {game.opportunity.market}</p>
                  </div>

                  <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                    <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Sports Intelligence Score</p>
                    <p className="mt-3 text-3xl font-semibold text-emerald-400">
                      {game.opportunity.sportsIntelligenceScore.score.toFixed(1)}
                    </p>
                    <p className="mt-2 text-sm text-zinc-500">{game.opportunity.sportsIntelligenceScore.grade}</p>
                  </div>

                  <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                    <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Model edge</p>
                    <p className="mt-3 text-2xl font-semibold text-white">+{game.opportunity.edge.toFixed(1)}%</p>
                  </div>

                  <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                    <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Market intelligence</p>
                    <p className="mt-3 text-2xl font-semibold text-white">{game.opportunity.marketIntelligence.score.toFixed(1)}/100</p>
                    <p className="mt-2 text-sm text-zinc-500">{game.opportunity.marketIntelligence.signal}</p>
                  </div>
                </div>
              ) : (
                <div className="mt-8 rounded-2xl border border-dashed border-white/10 bg-black/10 p-5 text-sm text-zinc-500">
                  No qualified opportunity is currently available for this matchup.
                </div>
              )}

              <div className="mt-6">
                <Link
                  href={game.opportunity ? `/opportunities/${game.opportunity.id}` : "/opportunities"}
                  className="inline-flex items-center rounded-full border border-white/10 px-4 py-2 text-sm text-zinc-300 transition hover:border-white/20 hover:text-white"
                >
                  View full analysis →
                </Link>
              </div>
            </article>
          ))}
        </div>
      </div>
    </main>
  );
}
