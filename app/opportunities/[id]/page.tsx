"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

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
  dataCompleteness: number;
  marketConfidence: number;
  modelConfidence: number;
  rank: number;
};

export default function OpportunityAnalysisPage() {
  const params = useParams<{ id: string }>();

  const [opportunity, setOpportunity] = useState<Opportunity | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadOpportunity() {
      try {
        const response = await fetch(
          `http://localhost:8000/api/opportunities/${params.id}`
        );

        if (!response.ok) {
          throw new Error("Failed to load opportunity");
        }

        const data: Opportunity = await response.json();
        setOpportunity(data);
      } catch (err) {
        console.error(err);
        setError("Unable to load this opportunity.");
      } finally {
        setLoading(false);
      }
    }

    if (params.id) {
      loadOpportunity();
    }
  }, [params.id]);

  function addToCard() {
    if (!opportunity) return;

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
  }

  if (loading) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:px-10">
          <p className="text-sm text-zinc-500">
            Loading opportunity analysis...
          </p>
        </div>
      </main>
    );
  }

  if (error || !opportunity) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:px-10">
          <p className="text-red-400">
            {error || "Opportunity not found."}
          </p>
        </div>
      </main>
    );
  }

  const probabilityGap =
    opportunity.modelProbability - opportunity.impliedProbability;

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-6xl px-6 py-10 lg:px-10">
        <div className="flex items-center justify-between">
          <Link
            href="/opportunities"
            className="text-sm text-zinc-500 transition hover:text-white"
          >
            ← Opportunities
          </Link>

          <Badge
            variant="outline"
            className="border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-400"
          >
            {opportunity.recommendation}
          </Badge>
        </div>

        <section className="mt-12">
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-zinc-600">
            {opportunity.matchup}
          </p>

          <div className="mt-4 flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h1 className="text-5xl font-semibold tracking-[-0.04em] md:text-7xl">
                {opportunity.pick}
              </h1>

              <p className="mt-4 text-base text-zinc-500">
                {opportunity.book} •{" "}
                {opportunity.price > 0 ? "+" : ""}
                {opportunity.price}
              </p>
            </div>

            <div className="flex gap-10">
              <div>
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Confidence
                </p>

                <p className="mt-1 text-3xl font-semibold">
                  {opportunity.confidence}
                </p>
              </div>

              <div>
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Model Edge
                </p>

                <p className="mt-1 text-3xl font-semibold text-emerald-400">
                  +{opportunity.edge.toFixed(1)}%
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="mt-10 rounded-3xl border border-white/[0.08] bg-[linear-gradient(135deg,#111823_0%,#0C121A_100%)] p-8 lg:p-10">
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-400">
            Model Recommendation
          </p>

          <h2 className="mt-3 max-w-4xl text-3xl font-semibold tracking-tight">
            The model sees a {probabilityGap.toFixed(1)} percentage-point gap
            versus the market.
          </h2>

          <p className="mt-5 max-w-3xl text-base leading-8 text-zinc-400">
            The model estimates this position at{" "}
            {opportunity.modelProbability.toFixed(1)}% probability compared
            with a market-implied probability of{" "}
            {opportunity.impliedProbability.toFixed(1)}%. Current model edge is
            +{opportunity.edge.toFixed(1)}%, with expected value of $
            {opportunity.evPerDollar.toFixed(3)} per $1 risked.
          </p>

          <div className="mt-8 flex flex-wrap gap-3">
            <Button
              onClick={addToCard}
              className="h-11 bg-white px-6 text-black hover:bg-zinc-200"
            >
              Add to My Card
            </Button>

            <Link href="/my-card">
              <Button
                variant="outline"
                className="h-11 border-white/10 bg-transparent px-6 text-white hover:bg-white/[0.05]"
              >
                View My Card →
              </Button>
            </Link>
          </div>
        </section>

        <section className="mt-8 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Model Probability
            </p>
            <p className="mt-3 text-2xl font-semibold">
              {opportunity.modelProbability.toFixed(1)}%
            </p>
          </div>

          <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Market Implied
            </p>
            <p className="mt-3 text-2xl font-semibold">
              {opportunity.impliedProbability.toFixed(1)}%
            </p>
          </div>

          <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Kelly 20%
            </p>
            <p className="mt-3 text-2xl font-semibold">
              {(opportunity.kelly20 * 100).toFixed(1)}%
            </p>
          </div>

          <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Fair Odds
            </p>
            <p className="mt-3 text-2xl font-semibold">
              {opportunity.fairOdds}
            </p>
          </div>
        </section>

        <section className="mt-8 grid gap-4 lg:grid-cols-2">
          <article className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-700">
              Model Quality
            </p>

            <div className="mt-6 space-y-5">
              <div>
                <div className="flex justify-between text-sm">
                  <span className="text-zinc-500">Data completeness</span>
                  <span>{opportunity.dataCompleteness.toFixed(0)}%</span>
                </div>

                <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/[0.05]">
                  <div
                    className="h-full bg-white"
                    style={{ width: `${opportunity.dataCompleteness}%` }}
                  />
                </div>
              </div>

              <div>
                <div className="flex justify-between text-sm">
                  <span className="text-zinc-500">Market confidence</span>
                  <span>{opportunity.marketConfidence.toFixed(0)}%</span>
                </div>

                <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/[0.05]">
                  <div
                    className="h-full bg-white"
                    style={{ width: `${opportunity.marketConfidence}%` }}
                  />
                </div>
              </div>

              <div>
                <div className="flex justify-between text-sm">
                  <span className="text-zinc-500">Model confidence</span>
                  <span>{opportunity.modelConfidence.toFixed(0)}%</span>
                </div>

                <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/[0.05]">
                  <div
                    className="h-full bg-white"
                    style={{ width: `${opportunity.modelConfidence}%` }}
                  />
                </div>
              </div>
            </div>
          </article>

          <article className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-700">
              Position Sizing
            </p>

            <div className="mt-5 space-y-5">
              <div>
                <p className="text-sm text-zinc-500">Full Kelly</p>
                <p className="mt-1 text-2xl font-semibold">
                  {(opportunity.kellyFull * 100).toFixed(1)}%
                </p>
              </div>

              <div>
                <p className="text-sm text-zinc-500">20% Kelly</p>
                <p className="mt-1 text-2xl font-semibold">
                  {(opportunity.kelly20 * 100).toFixed(1)}%
                </p>
              </div>

              <div>
                <p className="text-sm text-zinc-500">Expected value / $1</p>
                <p className="mt-1 text-2xl font-semibold text-emerald-400">
                  +${opportunity.evPerDollar.toFixed(3)}
                </p>
              </div>
            </div>
          </article>
        </section>

        <section className="mt-8 rounded-3xl border border-emerald-400/15 bg-emerald-400/[0.035] p-8">
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-400">
            Bottom Line
          </p>

          <h2 className="mt-3 text-3xl font-semibold">
            {opportunity.pick} is currently ranked #{opportunity.rank}.
          </h2>

          <p className="mt-4 max-w-3xl text-sm leading-7 text-zinc-400">
            This recommendation is coming directly from NFL Analytics OS v1.9.
            It should be reassessed whenever the available price, market line,
            model inputs, or underlying data change.
          </p>
        </section>
      </div>
    </main>
  );
}