"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

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

export default function Home() {
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadData() {
      try {
        const response = await fetch(
          "http://localhost:8000/api/opportunities?limit=10"
        );

        if (!response.ok) {
          throw new Error("Failed to load opportunities");
        }

        const data: ApiResponse = await response.json();

        setOpportunities(data.opportunities);
      } catch (err) {
        console.error(err);
        setError("Unable to load live model data.");
      } finally {
        setLoading(false);
      }
    }

    loadData();
  }, []);

  if (loading) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-[1320px] px-6 py-16 lg:px-10">
          <p className="text-sm text-zinc-500">
            Loading Sports Intelligence...
          </p>
        </div>
      </main>
    );
  }

  if (error) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-[1320px] px-6 py-16 lg:px-10">
          <p className="text-red-400">{error}</p>
        </div>
      </main>
    );
  }

  const topOpportunity = opportunities[0];

  const strongestEdge =
    opportunities.length > 0
      ? Math.max(...opportunities.map((item) => item.edge))
      : 0;

  const highestConfidence =
    opportunities.length > 0
      ? Math.max(...opportunities.map((item) => item.confidence))
      : 0;

  const strongBets = opportunities.filter(
    (item) => item.recommendation === "STRONG BET"
  );

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <header className="border-b border-white/[0.06]">
        <div className="mx-auto flex max-w-[1320px] items-center justify-between px-6 py-5 lg:px-10">
          <div>
            <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-zinc-600">
              NFL Intelligence Engine
            </p>

            <h1 className="mt-1 text-xl font-semibold tracking-tight">
              Live Decision Dashboard
            </h1>
          </div>

          <Badge
            variant="outline"
            className="border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-400"
          >
            Model Live
          </Badge>
        </div>
      </header>

      <div className="mx-auto max-w-[1320px] px-6 py-10 lg:px-10">
        <section>
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-zinc-600">
            Today&apos;s intelligence
          </p>

          <div className="mt-3 flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h2 className="max-w-4xl text-4xl font-semibold tracking-[-0.03em] md:text-5xl">
                {opportunities.length} ranked opportunities are currently
                available.
              </h2>

              <p className="mt-4 max-w-2xl text-base leading-7 text-zinc-500">
                Your dashboard is now reading directly from NFL Analytics OS
                v1.9 and ranking opportunities using model probability, market
                price, EV, confidence, and Kelly sizing.
              </p>

              <div className="mt-6 flex flex-wrap gap-3">
                <Link href="/opportunities">
                  <Button className="h-11 bg-white px-5 text-black hover:bg-zinc-200">
                    Review Opportunities →
                  </Button>
                </Link>

                <Link href="/briefing">
                  <Button
                    variant="outline"
                    className="h-11 border-white/10 bg-transparent px-5 text-white hover:bg-white/[0.05]"
                  >
                    Open Briefing
                  </Button>
                </Link>
              </div>
            </div>

            <div className="flex flex-wrap gap-8">
              <div>
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Strong Bets
                </p>
                <p className="mt-1 text-xl font-semibold">
                  {strongBets.length}
                </p>
              </div>

              <div>
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Highest Confidence
                </p>
                <p className="mt-1 text-xl font-semibold">
                  {highestConfidence}
                </p>
              </div>

              <div>
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Strongest Edge
                </p>
                <p className="mt-1 text-xl font-semibold text-emerald-400">
                  +{strongestEdge.toFixed(1)}%
                </p>
              </div>
            </div>
          </div>
        </section>

        {topOpportunity && (
          <section className="mt-10 overflow-hidden rounded-3xl border border-white/[0.08] bg-[linear-gradient(135deg,#121823_0%,#0D121A_100%)] shadow-2xl shadow-black/30">
            <div className="grid lg:grid-cols-[1.3fr_0.7fr]">
              <div className="p-8 lg:p-10">
                <div className="flex items-center gap-3">
                  <Badge className="bg-emerald-400 text-black hover:bg-emerald-400">
                    #1 Opportunity
                  </Badge>

                  <span className="text-xs text-zinc-600">
                    Highest-ranked position in the current model output
                  </span>
                </div>

                <p className="mt-8 text-sm text-zinc-500">
                  {topOpportunity.matchup}
                </p>

                <div className="mt-2 flex flex-wrap items-end gap-x-5 gap-y-2">
                  <h3 className="text-4xl font-semibold tracking-tight">
                    {topOpportunity.pick}
                  </h3>

                  <span className="pb-1 text-sm text-zinc-500">
                    {topOpportunity.book}
                  </span>
                </div>

                <p className="mt-4 max-w-2xl text-base leading-7 text-zinc-400">
                  Model probability is{" "}
                  {topOpportunity.modelProbability.toFixed(1)}% versus a
                  market-implied probability of{" "}
                  {topOpportunity.impliedProbability.toFixed(1)}%, creating a
                  current model edge of +{topOpportunity.edge.toFixed(1)}%.
                </p>

                <div className="mt-8 flex flex-wrap gap-3">
                  <Link href={`/opportunities/${topOpportunity.id}`}>
                    <Button className="h-11 bg-white px-5 text-black hover:bg-zinc-200">
                      View Full Analysis →
                    </Button>
                  </Link>

                  <Link href="/opportunities">
                    <Button
                      variant="outline"
                      className="h-11 border-white/10 bg-transparent px-5 text-white hover:bg-white/[0.05]"
                    >
                      View All Opportunities
                    </Button>
                  </Link>
                </div>
              </div>

              <div className="border-t border-white/[0.07] bg-black/10 p-8 lg:border-l lg:border-t-0 lg:p-10">
                <p className="text-xs uppercase tracking-[0.18em] text-zinc-600">
                  Decision Snapshot
                </p>

                <div className="mt-7 space-y-6">
                  <div className="flex items-end justify-between border-b border-white/[0.07] pb-5">
                    <span className="text-sm text-zinc-500">
                      Confidence
                    </span>
                    <span className="text-2xl font-semibold">
                      {topOpportunity.confidence}
                    </span>
                  </div>

                  <div className="flex items-end justify-between border-b border-white/[0.07] pb-5">
                    <span className="text-sm text-zinc-500">
                      Model Edge
                    </span>
                    <span className="text-2xl font-semibold text-emerald-400">
                      +{topOpportunity.edge.toFixed(1)}%
                    </span>
                  </div>

                  <div className="flex items-end justify-between border-b border-white/[0.07] pb-5">
                    <span className="text-sm text-zinc-500">
                      EV / $1
                    </span>
                    <span className="text-2xl font-semibold">
                      +${topOpportunity.evPerDollar.toFixed(3)}
                    </span>
                  </div>

                  <div className="flex items-end justify-between">
                    <span className="text-sm text-zinc-500">
                      Kelly 20%
                    </span>
                    <span className="text-sm font-medium text-zinc-200">
                      {(topOpportunity.kelly20 * 100).toFixed(1)}%
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </section>
        )}

        <section className="mt-8 grid gap-4 lg:grid-cols-3">
          {opportunities.slice(1, 4).map((opportunity) => (
            <Link
              key={opportunity.id}
              href={`/opportunities/${opportunity.id}`}
              className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6 transition hover:border-white/15 hover:bg-[#101721]"
            >
              <div className="flex items-center justify-between">
                <span className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  #{opportunity.rank}
                </span>

                <span className="text-xs text-emerald-400">
                  +{opportunity.edge.toFixed(1)}%
                </span>
              </div>

              <p className="mt-5 text-sm text-zinc-500">
                {opportunity.matchup}
              </p>

              <h3 className="mt-1 text-2xl font-semibold">
                {opportunity.pick}
              </h3>

              <p className="mt-2 text-sm text-zinc-600">
                {opportunity.book} • Confidence {opportunity.confidence}
              </p>
            </Link>
          ))}
        </section>

        <section className="mt-8 grid gap-4 lg:grid-cols-3">
          <Link
            href="/opportunities"
            className="rounded-2xl border border-white/[0.07] bg-[#0B1119] p-6 transition hover:border-white/15"
          >
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Opportunity Engine
            </p>

            <p className="mt-3 text-2xl font-semibold">
              {opportunities.length} ranked positions
            </p>

            <p className="mt-2 text-sm text-zinc-500">
              Review the current board ranked by model opportunity.
            </p>
          </Link>

          <Link
            href="/my-card"
            className="rounded-2xl border border-white/[0.07] bg-[#0B1119] p-6 transition hover:border-white/15"
          >
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              My Card
            </p>

            <p className="mt-3 text-2xl font-semibold">
              Portfolio review
            </p>

            <p className="mt-2 text-sm text-zinc-500">
              Review your saved positions, exposure, and model confidence.
            </p>
          </Link>

          <Link
            href="/briefing"
            className="rounded-2xl border border-white/[0.07] bg-[#0B1119] p-6 transition hover:border-white/15"
          >
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Briefing
            </p>

            <p className="mt-3 text-2xl font-semibold">
              Executive intelligence
            </p>

            <p className="mt-2 text-sm text-zinc-500">
              A distilled view of the information affecting today&apos;s
              decisions.
            </p>
          </Link>
        </section>
      </div>
    </main>
  );
}