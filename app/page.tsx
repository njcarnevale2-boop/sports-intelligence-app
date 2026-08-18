"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import FreshnessBadge from "@/components/ui/freshness-badge";
import { Button } from "@/components/ui/button";
import { fetchJson } from "./lib/api";
import { trackAnalyticsEvent } from "./lib/analytics";

type SportsIntelligenceScore = {
  score: number;
  recommendation: string;
  reasons: string[];
};

type Opportunity = {
  id: string;
  rank: number;
  eventId: string;
  market: string;
  side: string;
  pick: string;
  book: string;
  point: number;
  price: number;
  truePlayableTo?: number | null;
  truePlayableToStatus?: "AVAILABLE" | "UNAVAILABLE";
  truePlayableToReason?: string | null;
  currentWinProbability?: number | null;
  currentEV?: number | null;
  kelly20?: number | null;
  modelProbability: number;
  impliedProbability: number;
  edge: number;
  recommendation: string;
  sportsIntelligenceScore: SportsIntelligenceScore;
};

type ApiResponse = {
  count: number;
  week?: number;
  weekScheduledGames?: number;
  dataStatus?: string;
  lastUpdated?: string | null;
  opportunities: Opportunity[];
};

function formatPrice(n: number) {
  return n > 0 ? `+${n}` : `${n}`;
}

function formatLine(point: number) {
  return point > 0 ? `+${point}` : `${point}`;
}

function formatBestPrice(opp: Opportunity) {
  if (opp.market === "spread" || opp.market === "total") {
    return `${formatLine(opp.point)} ${formatPrice(opp.price)} · ${opp.book}`;
  }
  return `${formatPrice(opp.price)} · ${opp.book}`;
}

function formatPlayableTo(opp: Opportunity) {
  if (opp.truePlayableToStatus !== "AVAILABLE" || opp.truePlayableTo == null) {
    return "Not available yet";
  }

  if (opp.market === "spread" || opp.market === "total") {
    return formatLine(opp.truePlayableTo);
  }

  return formatPrice(opp.truePlayableTo);
}

function displayWinProbability(opp: Opportunity) {
  if (opp.currentWinProbability == null) return opp.modelProbability;
  return opp.currentWinProbability * 100;
}

function suggestedBet(opp: Opportunity) {
  if (opp.kelly20 == null) return "Unavailable";
  return `${(opp.kelly20 * 100).toFixed(1)}% bankroll`;
}

function statusLabel(opp: Opportunity) {
  const raw = (opp.sportsIntelligenceScore.recommendation || opp.recommendation || "").toUpperCase();
  if (raw.includes("STRONG") || raw.includes("ELITE")) return "STRONG BET";
  if (raw.includes("LEAN")) return "LEAN";
  return "BET";
}

export default function Home() {
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [freshnessStatus, setFreshnessStatus] = useState<{ dataStatus?: string; lastUpdated?: string | null }>({});
  const [week, setWeek] = useState<number | null>(null);
  const [gamesAnalyzed, setGamesAnalyzed] = useState<number>(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadData() {
      try {
        setLoading(true);
        setError("");

        void trackAnalyticsEvent("HomeViewed", { page: "home" });

        const data = await fetchJson<ApiResponse>("/api/opportunities?limit=100");

        setOpportunities(data.opportunities ?? []);
        setFreshnessStatus({ dataStatus: data.dataStatus, lastUpdated: data.lastUpdated });
        setWeek(typeof data.week === "number" ? data.week : null);
        setGamesAnalyzed(typeof data.weekScheduledGames === "number" ? data.weekScheduledGames : 0);
      } catch (err) {
        console.error(err);
        setError("Unable to load live model data.");
      } finally {
        setLoading(false);
      }
    }

    void loadData();
  }, []);

  const sia3 = useMemo(() => {
    return [...opportunities]
      .sort((a, b) => a.rank - b.rank)
      .slice(0, 3);
  }, [opportunities]);

  const headline = useMemo(() => {
    if (sia3.length === 0) return "NO SIA PICKS YET";
    if (sia3.length === 1) return "1 SIA PICK THIS WEEK";
    if (sia3.length === 2) return "2 SIA PICKS THIS WEEK";
    return "THE SIA 3";
  }, [sia3.length]);

  if (loading) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:px-10">
          <p className="text-sm text-zinc-500">Loading SIA picks...</p>
        </div>
      </main>
    );
  }

  if (error) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:px-10">
          <p className="text-red-400">{error}</p>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <header className="border-b border-white/[0.06]">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5 lg:px-10">
          <div>
            <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-zinc-600">Sports Intelligence</p>
            <h1 className="mt-1 text-xl font-semibold tracking-tight">Complex Engine. Simple Answer.</h1>
          </div>
          <div className="flex items-center gap-3">
            {freshnessStatus.dataStatus && (
              <FreshnessBadge status={freshnessStatus.dataStatus} lastUpdated={freshnessStatus.lastUpdated} label="Model" />
            )}
            <Link href="/games">
              <Button variant="outline" className="h-10 border-white/10 bg-transparent text-white hover:bg-white/[0.05]">Games Hub</Button>
            </Link>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-6 py-8 lg:px-10">
        <section className="rounded-3xl border border-white/[0.08] bg-[#0B1119] p-6 md:p-8">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-zinc-600">SIA Picks</p>
              <h2 className="mt-2 text-3xl font-semibold tracking-tight md:text-4xl">{headline}</h2>
              <p className="mt-2 text-sm text-zinc-500">
                {week != null ? `Week ${week}` : "Current week"} · {gamesAnalyzed} Games Analyzed
              </p>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <Badge variant="outline" className="border-white/[0.08] bg-white/[0.03] text-zinc-300">{opportunities.length} Qualified</Badge>
            </div>
          </div>

          {sia3.length === 0 ? (
            <div className="mt-6 rounded-2xl border border-dashed border-white/[0.1] p-5 text-zinc-400">
              SIA analyzed {gamesAnalyzed} games but none currently meet our betting criteria.
            </div>
          ) : (
            <div className="mt-6 grid gap-4 lg:grid-cols-3">
              {sia3.map((opp, idx) => (
                <article key={opp.id} className="rounded-2xl border border-white/[0.08] bg-black/20 p-5">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-600">#{idx + 1}</p>
                  <h3 className="mt-2 text-2xl font-semibold text-white">{opp.pick}</h3>
                  <p className="mt-2 text-sm text-zinc-300">{opp.sportsIntelligenceScore.score.toFixed(1)} · {statusLabel(opp)}</p>
                  <div className="mt-4 space-y-2 text-sm">
                    <p className="text-zinc-400">
                      <span className="text-zinc-500">BET:</span> <span className="text-zinc-200">{opp.pick}</span>
                    </p>
                    <p className="text-zinc-400">
                      <span className="text-zinc-500">BEST PRICE:</span> <span className="text-zinc-200">{formatBestPrice(opp)}</span>
                    </p>
                    <p className="text-zinc-400">
                      <span className="text-zinc-500">PLAYABLE TO:</span> <span className="text-zinc-200">{formatPlayableTo(opp)}</span>
                    </p>
                    <p className="text-zinc-400">
                      <span className="text-zinc-500">SI SCORE:</span> <span className="text-zinc-200">{opp.sportsIntelligenceScore.score.toFixed(1)}</span>
                    </p>
                    <p className="text-zinc-400">
                      <span className="text-zinc-500">SUGGESTED BET:</span> <span className="text-zinc-200">{suggestedBet(opp)}</span>
                    </p>
                  </div>
                  <div className="mt-4 flex gap-2">
                    <Link href={`/games/${opp.eventId}?ask=${encodeURIComponent("Why is this in The SIA 3?")}`}>
                      <Button className="h-9 bg-white px-4 text-black hover:bg-zinc-200">WHY?</Button>
                    </Link>
                    <Link href={`/games/${opp.eventId}`}>
                      <Button variant="outline" className="h-9 border-white/10 bg-transparent px-4 text-white hover:bg-white/[0.05]">GAME INTEL</Button>
                    </Link>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="mt-8 grid gap-4 md:grid-cols-3">
          {opportunities.slice(0, 3).map((opp) => (
            <div key={`${opp.id}-secondary`} className="rounded-2xl border border-white/[0.07] bg-[#0B1119] p-5">
              <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-700">SIA Win/Cover Probability</p>
              <p className="mt-2 text-2xl font-semibold text-white">{Math.round(displayWinProbability(opp))}%</p>
              <p className="mt-2 text-[10px] uppercase tracking-[0.16em] text-zinc-700">Market Implied</p>
              <p className="mt-1 text-xl font-semibold text-zinc-300">{Math.round(opp.impliedProbability)}%</p>
              <p className="mt-2 text-[10px] uppercase tracking-[0.16em] text-zinc-700">Difference</p>
              <p className="mt-1 text-lg font-semibold text-emerald-400">+{Math.round(displayWinProbability(opp) - opp.impliedProbability)} percentage points</p>
            </div>
          ))}
        </section>
      </div>
    </main>
  );
}
