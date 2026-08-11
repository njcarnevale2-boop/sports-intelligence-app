"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

type AlternateBook = {
  book: string;
  point: number;
  price: number;
  edge: number;
  evPerDollar: number;
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
  alternateBooks?: AlternateBook[];
};

function formatOdds(price: number) {
  return price > 0 ? `+${price}` : `${price}`;
}

function formatPoint(
  market: string,
  side: string,
  point: number
) {
  if (market === "spread") {
    return point > 0 ? `+${point}` : `${point}`;
  }

  if (market === "total") {
    return `${side.toUpperCase()} ${point}`;
  }

  return `${point}`;
}

export default function OpportunityAnalysisPage() {
  const params = useParams<{ id: string }>();

  const [opportunity, setOpportunity] =
    useState<Opportunity | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [added, setAdded] = useState(false);

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

        const saved = localStorage.getItem(
          "sports-intelligence-card"
        );

        if (saved) {
          try {
            const card: Opportunity[] = JSON.parse(saved);

            setAdded(
              card.some((bet) => bet.id === data.id)
            );
          } catch {
            setAdded(false);
          }
        }
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

    const existing = localStorage.getItem(
      "sports-intelligence-card"
    );

    let currentCard: Opportunity[] = [];

    if (existing) {
      try {
        currentCard = JSON.parse(existing);
      } catch {
        currentCard = [];
      }
    }

    const alreadyExists = currentCard.some(
      (bet) => bet.id === opportunity.id
    );

    if (!alreadyExists) {
      localStorage.setItem(
        "sports-intelligence-card",
        JSON.stringify([
          ...currentCard,
          opportunity,
        ])
      );
    }

    setAdded(true);
  }

  if (loading) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:px-10">
          <p className="text-sm text-zinc-500">
            Loading executive analysis...
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
    opportunity.modelProbability -
    opportunity.impliedProbability;

  const alternateBooks =
    opportunity.alternateBooks ?? [];

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-6xl px-6 py-10 lg:px-10">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <Link
            href="/opportunities"
            className="text-sm text-zinc-500 transition hover:text-white"
          >
            ← Opportunities
          </Link>

          <div className="flex items-center gap-3">
            <span className="text-xs text-zinc-600">
              Model Rank #{opportunity.rank}
            </span>

            <Badge
              variant="outline"
              className="border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-400"
            >
              {opportunity.recommendation}
            </Badge>
          </div>
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

              <div className="mt-4 flex flex-wrap items-center gap-3">
                <Badge className="bg-white text-black hover:bg-white">
                  Best Line
                </Badge>

                <span className="text-sm text-zinc-400">
                  {opportunity.book}
                </span>

                <span className="text-sm text-zinc-600">
                  {formatOdds(opportunity.price)}
                </span>
              </div>
            </div>

            <div className="flex flex-wrap gap-10">
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

              <div>
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  EV / $1
                </p>

                <p className="mt-1 text-3xl font-semibold">
                  +${opportunity.evPerDollar.toFixed(3)}
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="mt-10 rounded-3xl border border-emerald-400/15 bg-[linear-gradient(135deg,#111A18_0%,#0C121A_100%)] p-8 lg:p-10">
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-400">
            Executive Recommendation
          </p>

          <h2 className="mt-3 max-w-4xl text-3xl font-semibold tracking-tight">
            The model sees a{" "}
            {probabilityGap.toFixed(1)} percentage-point
            probability advantage over the market.
          </h2>

          <p className="mt-5 max-w-3xl text-base leading-8 text-zinc-400">
            NFL Analytics OS estimates this position at{" "}
            {opportunity.modelProbability.toFixed(1)}%
            versus a market-implied probability of{" "}
            {opportunity.impliedProbability.toFixed(1)}%.
            The current best available price is{" "}
            {opportunity.pick} at {opportunity.book} for{" "}
            {formatOdds(opportunity.price)}.
          </p>

          <div className="mt-8 flex flex-wrap gap-3">
            <Button
              onClick={addToCard}
              disabled={added}
              className={
                added
                  ? "h-11 bg-emerald-400/10 px-6 text-emerald-300"
                  : "h-11 bg-white px-6 text-black hover:bg-zinc-200"
              }
            >
              {added
                ? "Added to My Card ✓"
                : "Add to My Card"}
            </Button>

            <Link href="/my-card">
              <Button
                variant="outline"
                className="h-11 border-white/10 bg-transparent px-6 text-white hover:bg-white/[0.05]"
              >
                Review My Card →
              </Button>
            </Link>
          </div>
        </section>

        <section className="mt-8">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-700">
              Market Intelligence
            </p>

            <h2 className="mt-2 text-2xl font-semibold">
              Best available line across sportsbooks.
            </h2>
          </div>

          <div className="mt-5 overflow-hidden rounded-3xl border border-white/[0.08] bg-[#0D131C]">
            <div className="grid grid-cols-[1.4fr_0.8fr_0.8fr_0.8fr] gap-3 border-b border-white/[0.07] px-6 py-4 text-[11px] uppercase tracking-[0.14em] text-zinc-700">
              <span>Sportsbook</span>
              <span>Line</span>
              <span>Price</span>
              <span>EV / $1</span>
            </div>

            <div className="grid grid-cols-[1.4fr_0.8fr_0.8fr_0.8fr] gap-3 bg-emerald-400/[0.035] px-6 py-5">
              <div className="flex items-center gap-2">
                <span className="font-semibold">
                  {opportunity.book}
                </span>

                <Badge className="bg-emerald-400 text-black hover:bg-emerald-400">
                  Best
                </Badge>
              </div>

              <span className="font-medium">
                {formatPoint(
                  opportunity.market,
                  opportunity.side,
                  opportunity.point
                )}
              </span>

              <span className="font-medium">
                {formatOdds(opportunity.price)}
              </span>

              <span className="font-medium text-emerald-400">
                +${opportunity.evPerDollar.toFixed(3)}
              </span>
            </div>

            {alternateBooks.map((book) => (
              <div
                key={`${book.book}-${book.point}-${book.price}`}
                className="grid grid-cols-[1.4fr_0.8fr_0.8fr_0.8fr] gap-3 border-t border-white/[0.06] px-6 py-5 text-sm"
              >
                <span className="text-zinc-300">
                  {book.book}
                </span>

                <span className="text-zinc-400">
                  {formatPoint(
                    opportunity.market,
                    opportunity.side,
                    book.point
                  )}
                </span>

                <span className="text-zinc-400">
                  {formatOdds(book.price)}
                </span>

                <span className="text-zinc-400">
                  +${book.evPerDollar.toFixed(3)}
                </span>
              </div>
            ))}

            {alternateBooks.length === 0 && (
              <div className="border-t border-white/[0.06] px-6 py-6">
                <p className="text-sm text-zinc-600">
                  No alternate sportsbook prices are currently
                  available for this position.
                </p>
              </div>
            )}
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
              20% Kelly
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
              {formatOdds(opportunity.fairOdds)}
            </p>
          </div>
        </section>

        <section className="mt-8 grid gap-4 lg:grid-cols-2">
          <article className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-700">
              Signal Quality
            </p>

            <h3 className="mt-3 text-2xl font-semibold">
              Confidence behind the recommendation.
            </h3>

            <div className="mt-6 space-y-5">
              {[
                {
                  label: "Data completeness",
                  value: opportunity.dataCompleteness,
                },
                {
                  label: "Market confidence",
                  value: opportunity.marketConfidence,
                },
                {
                  label: "Model confidence",
                  value: opportunity.modelConfidence,
                },
              ].map((metric) => (
                <div key={metric.label}>
                  <div className="flex justify-between text-sm">
                    <span className="text-zinc-500">
                      {metric.label}
                    </span>

                    <span>
                      {metric.value.toFixed(0)}%
                    </span>
                  </div>

                  <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/[0.05]">
                    <div
                      className="h-full bg-white"
                      style={{
                        width: `${metric.value}%`,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </article>

          <article className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-700">
              Position Sizing
            </p>

            <h3 className="mt-3 text-2xl font-semibold">
              Model-derived allocation guidance.
            </h3>

            <div className="mt-6 space-y-5">
              <div className="flex items-end justify-between border-b border-white/[0.07] pb-4">
                <span className="text-sm text-zinc-500">
                  Full Kelly
                </span>

                <span className="text-xl font-semibold">
                  {(opportunity.kellyFull * 100).toFixed(1)}%
                </span>
              </div>

              <div className="flex items-end justify-between border-b border-white/[0.07] pb-4">
                <span className="text-sm text-zinc-500">
                  20% Kelly
                </span>

                <span className="text-xl font-semibold">
                  {(opportunity.kelly20 * 100).toFixed(1)}%
                </span>
              </div>

              <div className="flex items-end justify-between">
                <span className="text-sm text-zinc-500">
                  Expected Value / $1
                </span>

                <span className="text-xl font-semibold text-emerald-400">
                  +${opportunity.evPerDollar.toFixed(3)}
                </span>
              </div>
            </div>
          </article>
        </section>

        <section className="mt-8 grid gap-4 lg:grid-cols-2">
          <article className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-700">
              Supporting Case
            </p>

            <h3 className="mt-3 text-2xl font-semibold">
              What the current data supports.
            </h3>

            <div className="mt-5 space-y-4 text-sm leading-7 text-zinc-500">
              <p>
                The model probability exceeds the current
                market-implied probability by{" "}
                {probabilityGap.toFixed(1)} percentage
                points.
              </p>

              <p>
                The best available line currently produces
                +{opportunity.edge.toFixed(1)}% model edge
                and +${opportunity.evPerDollar.toFixed(3)}
                expected value for every $1 risked.
              </p>

              <p>
                Line shopping matters because alternate
                sportsbooks may offer different points,
                prices, and expected value.
              </p>
            </div>
          </article>

          <article className="rounded-3xl border border-amber-400/15 bg-amber-400/[0.03] p-7">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-amber-400">
              Risk Factors
            </p>

            <h3 className="mt-3 text-2xl font-semibold">
              What still needs monitoring.
            </h3>

            <div className="mt-5 space-y-4 text-sm leading-7 text-zinc-500">
              <p>
                The recommendation can weaken if the market
                moves away from the current best available
                number.
              </p>

              <p>
                Injury, weather, and other contextual data
                are not yet surfaced on this page as live
                feeds.
              </p>

              <p>
                Kelly sizing is model-derived and should not
                be interpreted as guaranteed-return sizing.
              </p>
            </div>
          </article>
        </section>

        <section className="mt-8 rounded-3xl border border-emerald-400/15 bg-emerald-400/[0.035] p-8">
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-400">
            Bottom Line
          </p>

          <h2 className="mt-3 text-3xl font-semibold">
            {opportunity.pick} is currently a{" "}
            {opportunity.recommendation.toLowerCase()}.
          </h2>

          <p className="mt-4 max-w-3xl text-sm leading-7 text-zinc-400">
            The current best line is available at{" "}
            {opportunity.book}. The model sees a +
            {opportunity.edge.toFixed(1)}% edge with{" "}
            {opportunity.confidence} confidence. Continue
            monitoring the market because a change in line
            or price can materially alter the value of this
            position.
          </p>

          <div className="mt-7 flex flex-wrap gap-3">
            <Button
              onClick={addToCard}
              disabled={added}
              className={
                added
                  ? "bg-emerald-400/10 text-emerald-300"
                  : "bg-white text-black hover:bg-zinc-200"
              }
            >
              {added
                ? "Added to My Card ✓"
                : "Add to My Card"}
            </Button>

            <Link href="/opportunities">
              <Button
                variant="outline"
                className="border-white/10 bg-transparent text-white hover:bg-white/[0.05]"
              >
                Back to Opportunities
              </Button>
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}