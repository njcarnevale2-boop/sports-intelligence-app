"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fetchJson } from "../lib/api";

type Opportunity = {
  id: string;
  eventId: string;
  commenceTime: string;
  matchup: string;
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
  rank: number;
};

type ApiResponse = {
  count: number;
  source: string;
  opportunities: Opportunity[];
};

export default function BriefingPage() {
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadBriefing() {
      try {
        const data = await fetchJson<ApiResponse>("/api/opportunities?limit=10");
        setOpportunities(data.opportunities);
      } catch (err) {
        console.error(err);
        setError("Unable to load today's briefing.");
      } finally {
        setLoading(false);
      }
    }

    loadBriefing();
  }, []);

  const topOpportunity = opportunities[0];

  const strongBets = useMemo(
    () =>
      opportunities.filter(
        (item) => item.recommendation === "STRONG BET"
      ),
    [opportunities]
  );

  const averageEdge = useMemo(() => {
    if (opportunities.length === 0) return 0;

    return (
      opportunities.reduce((sum, item) => sum + item.edge, 0) /
      opportunities.length
    );
  }, [opportunities]);

  const averageConfidence = useMemo(() => {
    if (opportunities.length === 0) return 0;

    return (
      opportunities.reduce(
        (sum, item) => sum + item.confidence,
        0
      ) / opportunities.length
    );
  }, [opportunities]);

  const totalKelly = useMemo(() => {
    return opportunities.reduce(
      (sum, item) => sum + item.kelly20,
      0
    );
  }, [opportunities]);

  if (loading) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:px-10">
          <p className="text-sm text-zinc-500">
            Building executive briefing...
          </p>
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
      <div className="mx-auto max-w-6xl px-6 py-10 lg:px-10">
        <div className="flex items-center justify-between">
          <Link
            href="/"
            className="text-sm text-zinc-500 transition hover:text-white"
          >
            ← Home
          </Link>

          <Badge
            variant="outline"
            className="border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-400"
          >
            Live Model Briefing
          </Badge>
        </div>

        <section className="mt-14">
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-zinc-600">
            Executive Briefing
          </p>

          <h1 className="mt-4 max-w-4xl text-4xl font-semibold tracking-[-0.03em] md:text-6xl">
            Here&apos;s what deserves your attention right now.
          </h1>

          <p className="mt-5 max-w-3xl text-base leading-7 text-zinc-500">
            This briefing is generated from the current NFL Analytics OS
            opportunity board and summarizes the strongest model signals,
            current concentration, and the positions with the most decision
            value.
          </p>
        </section>

        <section className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Opportunities
            </p>
            <p className="mt-3 text-3xl font-semibold">
              {opportunities.length}
            </p>
          </div>

          <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Strong Bets
            </p>
            <p className="mt-3 text-3xl font-semibold">
              {strongBets.length}
            </p>
          </div>

          <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Avg Confidence
            </p>
            <p className="mt-3 text-3xl font-semibold">
              {averageConfidence.toFixed(1)}
            </p>
          </div>

          <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Avg Edge
            </p>
            <p className="mt-3 text-3xl font-semibold text-emerald-400">
              +{averageEdge.toFixed(1)}%
            </p>
          </div>
        </section>

        {topOpportunity && (
          <section className="mt-8 rounded-3xl border border-emerald-400/15 bg-emerald-400/[0.035] p-8 lg:p-10">
            <div className="flex flex-col gap-8 lg:flex-row lg:items-center lg:justify-between">
              <div className="max-w-3xl">
                <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-400">
                  Lead Recommendation
                </p>

                <p className="mt-5 text-sm text-zinc-500">
                  {topOpportunity.matchup}
                </p>

                <h2 className="mt-1 text-4xl font-semibold tracking-tight">
                  {topOpportunity.pick}
                </h2>

                <p className="mt-4 text-base leading-7 text-zinc-400">
                  The model gives this position a{" "}
                  {topOpportunity.modelProbability.toFixed(1)}% estimated
                  probability versus a{" "}
                  {topOpportunity.impliedProbability.toFixed(1)}% market
                  implied probability. That produces a current edge of +
                  {topOpportunity.edge.toFixed(1)}% and expected value of $
                  {topOpportunity.evPerDollar.toFixed(3)} per $1 risked.
                </p>
              </div>

              <div className="min-w-[260px] rounded-2xl border border-white/[0.07] bg-black/10 p-6">
                <div className="flex justify-between border-b border-white/[0.07] pb-4">
                  <span className="text-sm text-zinc-500">
                    Confidence
                  </span>
                  <span className="font-semibold">
                    {topOpportunity.confidence}
                  </span>
                </div>

                <div className="mt-4 flex justify-between border-b border-white/[0.07] pb-4">
                  <span className="text-sm text-zinc-500">
                    Model Edge
                  </span>
                  <span className="font-semibold text-emerald-400">
                    +{topOpportunity.edge.toFixed(1)}%
                  </span>
                </div>

                <div className="mt-4 flex justify-between">
                  <span className="text-sm text-zinc-500">
                    Kelly 20%
                  </span>
                  <span className="font-semibold">
                    {(topOpportunity.kelly20 * 100).toFixed(1)}%
                  </span>
                </div>

                <Link
                  href={`/opportunities/${topOpportunity.id}`}
                  className="mt-6 flex h-11 items-center justify-center rounded-lg bg-white px-5 text-sm font-medium text-black transition hover:bg-zinc-200"
                >
                  Review Full Analysis →
                </Link>
              </div>
            </div>
          </section>
        )}

        <section className="mt-8 grid gap-4 lg:grid-cols-2">
          <article className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-700">
              Board Concentration
            </p>

            <h3 className="mt-3 text-2xl font-semibold">
              The current board is heavily concentrated in strong
              recommendations.
            </h3>

            <p className="mt-4 text-sm leading-7 text-zinc-500">
              {strongBets.length} of the top {opportunities.length} ranked
              positions are currently classified as STRONG BET. Average
              confidence is {averageConfidence.toFixed(1)}, with an average
              model edge of +{averageEdge.toFixed(1)}%.
            </p>
          </article>

          <article className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-700">
              Position Sizing Signal
            </p>

            <h3 className="mt-3 text-2xl font-semibold">
              Current recommended sizing is aggressive.
            </h3>

            <p className="mt-4 text-sm leading-7 text-zinc-500">
              The combined 20% Kelly allocation across the top{" "}
              {opportunities.length} opportunities is{" "}
              {(totalKelly * 100).toFixed(1)}%. This is a raw model signal,
              not a recommendation to deploy that amount simultaneously.
            </p>
          </article>
        </section>

        <section className="mt-8">
          <div className="flex items-end justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-700">
                Next Best Opportunities
              </p>

              <h3 className="mt-2 text-2xl font-semibold">
                Positions immediately behind the lead recommendation.
              </h3>
            </div>

            <Link
              href="/opportunities"
              className="text-sm text-zinc-500 transition hover:text-white"
            >
              View full board →
            </Link>
          </div>

          <div className="mt-5 grid gap-4 lg:grid-cols-3">
            {opportunities.slice(1, 4).map((opportunity) => (
              <Link
                key={opportunity.id}
                href={`/opportunities/${opportunity.id}`}
                className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6 transition hover:border-white/15 hover:bg-[#101721]"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs text-zinc-700">
                    #{opportunity.rank}
                  </span>

                  <span className="text-xs font-medium text-emerald-400">
                    +{opportunity.edge.toFixed(1)}%
                  </span>
                </div>

                <p className="mt-5 text-sm text-zinc-500">
                  {opportunity.matchup}
                </p>

                <h4 className="mt-1 text-2xl font-semibold">
                  {opportunity.pick}
                </h4>

                <p className="mt-2 text-sm text-zinc-600">
                  {opportunity.book} • Confidence{" "}
                  {opportunity.confidence}
                </p>
              </Link>
            ))}
          </div>
        </section>

        <section className="mt-8 rounded-3xl border border-white/[0.08] bg-[#0B1119] p-8">
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-700">
            Briefing Conclusion
          </p>

          <h2 className="mt-3 text-3xl font-semibold">
            The current board presents meaningful model value, led by{" "}
            {topOpportunity?.pick ?? "the highest-ranked opportunity"}.
          </h2>

          <p className="mt-4 max-w-3xl text-sm leading-7 text-zinc-500">
            Use the briefing as a high-level decision layer, then review each
            opportunity individually before adding exposure. The next version
            of this page can incorporate live market movement, injuries,
            weather, and portfolio conflicts as those feeds are connected.
          </p>

          <div className="mt-6 flex flex-wrap gap-3">
            <Link href="/opportunities">
              <Button className="h-11 bg-white px-5 text-black hover:bg-zinc-200">
                Review Opportunities →
              </Button>
            </Link>

            <Link href="/my-card">
              <Button
                variant="outline"
                className="h-11 border-white/10 bg-transparent px-5 text-white hover:bg-white/[0.05]"
              >
                Review My Card
              </Button>
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}