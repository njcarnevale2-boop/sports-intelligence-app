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

export default function OpportunitiesPage() {
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [added, setAdded] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadOpportunities() {
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
        setError("Unable to load model opportunities.");
      } finally {
        setLoading(false);
      }
    }

    loadOpportunities();
  }, []);

  function addToCard(opportunity: Opportunity) {
    const existing = localStorage.getItem("sports-intelligence-card");

    const currentCard: Opportunity[] = existing
      ? JSON.parse(existing)
      : [];

    const alreadyExists = currentCard.some(
      (bet) => bet.id === opportunity.id
    );

    if (!alreadyExists) {
      localStorage.setItem(
        "sports-intelligence-card",
        JSON.stringify([...currentCard, opportunity])
      );
    }

    setAdded((current) =>
      current.includes(opportunity.id)
        ? current
        : [...current, opportunity.id]
    );
  }

  if (loading) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:px-10">
          <p className="text-sm text-zinc-500">
            Loading model opportunities...
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

  const strongestEdge =
    opportunities.length > 0
      ? Math.max(...opportunities.map((item) => item.edge))
      : 0;

  const highestConfidence =
    opportunities.length > 0
      ? Math.max(...opportunities.map((item) => item.confidence))
      : 0;

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-6xl px-6 py-10 lg:px-10">
        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.2em] text-zinc-600">
              Live Model Opportunities
            </p>

            <h1 className="mt-3 text-4xl font-semibold tracking-[-0.03em] md:text-6xl">
              Today&apos;s best opportunities.
            </h1>

            <p className="mt-5 max-w-2xl text-base leading-7 text-zinc-500">
              Ranked directly from NFL Analytics OS v1.9 using model probability,
              market implied probability, EV, confidence, and Kelly sizing.
            </p>
          </div>

          <Link href="/my-card">
            <Button
              variant="outline"
              className="border-white/10 bg-transparent text-white hover:bg-white/[0.05]"
            >
              View My Card →
            </Button>
          </Link>
        </div>

        <div className="mt-10 flex flex-wrap items-center gap-8 border-y border-white/[0.07] py-5">
          <div>
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Opportunities
            </p>

            <p className="mt-1 text-xl font-semibold">
              {opportunities.length}
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

          <div>
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Highest Confidence
            </p>

            <p className="mt-1 text-xl font-semibold">
              {highestConfidence}
            </p>
          </div>
        </div>

        <section className="mt-8 space-y-5">
          {opportunities.map((opportunity) => {
            const isAdded = added.includes(opportunity.id);

            return (
              <article
                key={opportunity.id}
                className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7 md:p-8"
              >
                <div className="flex flex-col gap-8 lg:flex-row lg:items-center lg:justify-between">
                  <div className="max-w-2xl">
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-zinc-700">
                        #{opportunity.rank}
                      </span>

                      <Badge
                        variant="outline"
                        className="border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-400"
                      >
                        {opportunity.recommendation}
                      </Badge>
                    </div>

                    <p className="mt-5 text-sm text-zinc-500">
                      {opportunity.matchup}
                    </p>

                    <h2 className="mt-1 text-3xl font-semibold tracking-tight">
                      {opportunity.pick}
                    </h2>

                    <p className="mt-1 text-sm text-zinc-600">
                      {opportunity.book} • {opportunity.price > 0 ? "+" : ""}
                      {opportunity.price}
                    </p>

                    <div className="mt-5 grid gap-3 sm:grid-cols-3">
                      <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                        <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                          Model Prob
                        </p>
                        <p className="mt-2 font-semibold">
                          {opportunity.modelProbability}%
                        </p>
                      </div>

                      <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                        <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                          Market Implied
                        </p>
                        <p className="mt-2 font-semibold">
                          {opportunity.impliedProbability}%
                        </p>
                      </div>

                      <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                        <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                          EV / $1
                        </p>
                        <p className="mt-2 font-semibold">
                          ${opportunity.evPerDollar.toFixed(3)}
                        </p>
                      </div>
                    </div>
                  </div>

                  <div className="min-w-[300px]">
                    <div className="grid grid-cols-2 gap-3">
                      <div className="rounded-2xl border border-white/[0.07] bg-black/10 p-5">
                        <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                          Confidence
                        </p>

                        <p className="mt-2 text-2xl font-semibold">
                          {opportunity.confidence}
                        </p>
                      </div>

                      <div className="rounded-2xl border border-white/[0.07] bg-black/10 p-5">
                        <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                          Edge
                        </p>

                        <p className="mt-2 text-2xl font-semibold text-emerald-400">
                          +{opportunity.edge.toFixed(1)}%
                        </p>
                      </div>

                      <div className="rounded-2xl border border-white/[0.07] bg-black/10 p-5">
                        <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                          Kelly 20%
                        </p>

                        <p className="mt-2 text-xl font-semibold">
                          {(opportunity.kelly20 * 100).toFixed(1)}%
                        </p>
                      </div>

                      <div className="rounded-2xl border border-white/[0.07] bg-black/10 p-5">
                        <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                          Fair Odds
                        </p>

                        <p className="mt-2 text-xl font-semibold">
                          {opportunity.fairOdds}
                        </p>
                      </div>
                    </div>

                    <div className="mt-3 grid gap-3">
                      <Link href={`/opportunities/${opportunity.id}`}>
                        <Button
                          variant="outline"
                          className="h-11 w-full border-white/10 bg-transparent text-white hover:bg-white/[0.05]"
                        >
                          View Full Analysis →
                        </Button>
                      </Link>

                      <Button
                        onClick={() => addToCard(opportunity)}
                        disabled={isAdded}
                        className={
                          isAdded
                            ? "h-11 bg-emerald-400/10 text-emerald-300"
                            : "h-11 bg-white text-black hover:bg-zinc-200"
                        }
                      >
                        {isAdded ? "Added ✓" : "Add to My Card"}
                      </Button>

                      {isAdded && (
                        <Link href="/my-card">
                          <Button
                            variant="outline"
                            className="h-11 w-full border-white/10 bg-transparent text-white hover:bg-white/[0.05]"
                          >
                            View My Card →
                          </Button>
                        </Link>
                      )}
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
        </section>
      </div>
    </main>
  );
}