"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { fetchJson } from "../lib/api";

type ProfitPoint = {
  label: string;
  profit: number;
};

type PerformanceSummary = {
  overallROI: number;
  winRate: number;
  closingLineValue: number;
  totalTrackedRecommendations?: number;
  profitByMarket: ProfitPoint[];
  profitBySportsbook: ProfitPoint[];
  profitBySiScore: ProfitPoint[];
  profitByRecommendation: ProfitPoint[];
};

function formatPercent(value: number) {
  return `${value.toFixed(1)}%`;
}

export default function PerformancePage() {
  const [summary, setSummary] = useState<PerformanceSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadPerformance() {
      try {
        const data: PerformanceSummary = await fetchJson<PerformanceSummary>("/api/performance");
        setSummary(data);
      } catch (err) {
        console.error(err);
        setError("Performance history is not ready yet.");
      } finally {
        setLoading(false);
      }
    }

    loadPerformance();
  }, []);

  const hasHistory = useMemo(() => {
    if (!summary) return false;
    return Boolean(
      summary.profitByMarket.length ||
        summary.profitBySportsbook.length ||
        summary.profitBySiScore.length ||
        summary.profitByRecommendation.length ||
        summary.overallROI !== 0 ||
        summary.winRate !== 0 ||
        summary.closingLineValue !== 0
    );
  }, [summary]);

  if (loading) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:px-10">
          <p className="text-sm text-zinc-500">Loading live performance...</p>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-6xl px-6 py-10 lg:px-10">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Performance review</p>
            <h1 className="mt-3 text-4xl font-semibold tracking-tight">Performance</h1>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-zinc-500">
              Track realized results from the recommendations engine without fabricating outcomes.
            </p>
          </div>

          <Badge variant="outline" className={hasHistory ? "border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-400" : "border-white/10 bg-white/[0.04] text-zinc-300"}>
            {hasHistory ? "Live performance data" : "Not enough history yet"}
          </Badge>
        </div>

        {error ? (
          <div className="mt-8 rounded-3xl border border-white/10 bg-[#0B1119] p-8 text-sm text-zinc-400">
            {error}
          </div>
        ) : null}

        <section className="mt-10 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-2xl border border-white/10 bg-[#0B1119] p-6">
            <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-700">Overall ROI</p>
            <p className="mt-3 text-3xl font-semibold text-white">{summary?.overallROI ? formatPercent(summary.overallROI) : "—"}</p>
          </div>

          <div className="rounded-2xl border border-white/10 bg-[#0B1119] p-6">
            <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-700">Win rate</p>
            <p className="mt-3 text-3xl font-semibold text-white">{summary?.winRate ? formatPercent(summary.winRate) : "—"}</p>
          </div>

          <div className="rounded-2xl border border-white/10 bg-[#0B1119] p-6">
            <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-700">Closing line value</p>
            <p className="mt-3 text-3xl font-semibold text-white">{summary?.closingLineValue ? `${summary.closingLineValue.toFixed(2)}` : "—"}</p>
          </div>

          <div className="rounded-2xl border border-white/10 bg-[#0B1119] p-6">
            <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-700">Tracked recommendations</p>
            <p className="mt-3 text-3xl font-semibold text-white">{summary?.totalTrackedRecommendations ?? 0}</p>
          </div>
        </section>

        {hasHistory ? (
          <section className="mt-8 grid gap-4 lg:grid-cols-2">
            <div className="rounded-3xl border border-white/10 bg-[#0B1119] p-7">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600">Profit by market</p>
              <div className="mt-4 space-y-3">
                {summary?.profitByMarket.map((item) => (
                  <div key={item.label} className="flex items-center justify-between rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-zinc-400">
                    <span>{item.label}</span>
                    <span className="font-semibold text-white">{item.profit.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-3xl border border-white/10 bg-[#0B1119] p-7">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600">Profit by sportsbook</p>
              <div className="mt-4 space-y-3">
                {summary?.profitBySportsbook.map((item) => (
                  <div key={item.label} className="flex items-center justify-between rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-zinc-400">
                    <span>{item.label}</span>
                    <span className="font-semibold text-white">{item.profit.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-3xl border border-white/10 bg-[#0B1119] p-7">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600">Performance by SI Score band</p>
              <div className="mt-4 space-y-3">
                {summary?.profitBySiScore.map((item) => (
                  <div key={item.label} className="flex items-center justify-between rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-zinc-400">
                    <span>{item.label}</span>
                    <span className="font-semibold text-white">{item.profit.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="rounded-3xl border border-white/10 bg-[#0B1119] p-7">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600">Performance by recommendation level</p>
              <div className="mt-4 space-y-3">
                {summary?.profitByRecommendation.map((item) => (
                  <div key={item.label} className="flex items-center justify-between rounded-2xl border border-white/10 bg-black/20 px-4 py-3 text-sm text-zinc-400">
                    <span>{item.label}</span>
                    <span className="font-semibold text-white">{item.profit.toFixed(2)}</span>
                  </div>
                ))}
              </div>
            </div>
          </section>
        ) : (
          <section className="mt-8 rounded-3xl border border-dashed border-white/10 bg-[#0B1119] p-8">
            <h3 className="text-lg font-semibold text-white">Your performance history will appear here as tracked bets settle.</h3>
            <p className="mt-3 text-sm leading-7 text-zinc-500">
              SIA tracks your results automatically once you add bets to My Card. After games settle you'll see:
            </p>
            <ul className="mt-3 space-y-1.5 text-sm text-zinc-500">
              <li className="flex items-start gap-2"><span className="mt-1 text-zinc-700">•</span>Overall ROI and win rate</li>
              <li className="flex items-start gap-2"><span className="mt-1 text-zinc-700">•</span>Closing Line Value — did you beat the market before kickoff?</li>
              <li className="flex items-start gap-2"><span className="mt-1 text-zinc-700">•</span>Performance broken down by market, sportsbook, and SI Score band</li>
            </ul>
            <div className="mt-6">
              <Link href="/opportunities" className="inline-flex h-10 items-center gap-2 rounded-xl bg-white px-5 text-sm font-medium text-black transition hover:bg-zinc-200">
                Add a bet to My Card →
              </Link>
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
