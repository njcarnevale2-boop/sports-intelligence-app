"use client";

import { useEffect, useMemo, useState } from "react";
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

type SortOption = "rank" | "edge" | "ev" | "confidence";

export default function OpportunitiesPage() {
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [added, setAdded] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [sortBy, setSortBy] = useState<SortOption>("rank");
  const [sportsbookFilter, setSportsbookFilter] = useState("all");
  const [marketFilter, setMarketFilter] = useState("all");

  useEffect(() => {
    async function loadOpportunities() {
      try {
        const response = await fetch(
          "http://localhost:8000/api/opportunities?limit=100"
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

  useEffect(() => {
    const saved = localStorage.getItem("sports-intelligence-card");

    if (!saved) return;

    try {
      const card: Opportunity[] = JSON.parse(saved);
      setAdded(card.map((item) => item.id));
    } catch (err) {
      console.error("Unable to read saved card:", err);
    }
  }, []);

  function addToCard(opportunity: Opportunity) {
    const existing = localStorage.getItem("sports-intelligence-card");

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
      const updatedCard = [...currentCard, opportunity];

      localStorage.setItem(
        "sports-intelligence-card",
        JSON.stringify(updatedCard)
      );
    }

    setAdded((current) =>
      current.includes(opportunity.id)
        ? current
        : [...current, opportunity.id]
    );
  }

  const sportsbooks = useMemo(() => {
    return Array.from(
      new Set(opportunities.map((item) => item.book))
    ).sort();
  }, [opportunities]);

  const markets = useMemo(() => {
    return Array.from(
      new Set(opportunities.map((item) => item.market))
    ).sort();
  }, [opportunities]);

  const filteredOpportunities = useMemo(() => {
    const filtered = opportunities.filter((item) => {
      const sportsbookMatch =
        sportsbookFilter === "all" ||
        item.book === sportsbookFilter;

      const marketMatch =
        marketFilter === "all" ||
        item.market === marketFilter;

      return sportsbookMatch && marketMatch;
    });

    return [...filtered].sort((a, b) => {
      if (sortBy === "edge") {
        return b.edge - a.edge;
      }

      if (sortBy === "ev") {
        return b.evPerDollar - a.evPerDollar;
      }

      if (sortBy === "confidence") {
        return b.confidence - a.confidence;
      }

      return a.rank - b.rank;
    });
  }, [
    opportunities,
    sportsbookFilter,
    marketFilter,
    sortBy,
  ]);

  const strongestEdge =
    filteredOpportunities.length > 0
      ? Math.max(...filteredOpportunities.map((item) => item.edge))
      : 0;

  const highestConfidence =
    filteredOpportunities.length > 0
      ? Math.max(
          ...filteredOpportunities.map(
            (item) => item.confidence
          )
        )
      : 0;

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
              Filter and rank the live model board by edge, EV,
              confidence, sportsbook, and market.
            </p>
          </div>

          <Link
            href="/my-card"
            className="flex h-11 items-center justify-center rounded-lg border border-white/10 bg-transparent px-5 text-sm font-medium text-white transition hover:bg-white/[0.05]"
          >
            View My Card →
          </Link>
        </div>

        <section className="mt-8 rounded-3xl border border-white/[0.07] bg-[#0B1119] p-5">
          <div className="grid gap-4 md:grid-cols-3">
            <div>
              <label className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                Sort By
              </label>

              <select
                value={sortBy}
                onChange={(event) =>
                  setSortBy(event.target.value as SortOption)
                }
                className="mt-2 h-11 w-full rounded-xl border border-white/[0.08] bg-[#0D131C] px-4 text-sm text-white outline-none"
              >
                <option value="rank">Model Rank</option>
                <option value="edge">Highest Edge</option>
                <option value="ev">Highest EV</option>
                <option value="confidence">
                  Highest Confidence
                </option>
              </select>
            </div>

            <div>
              <label className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                Sportsbook
              </label>

              <select
                value={sportsbookFilter}
                onChange={(event) =>
                  setSportsbookFilter(event.target.value)
                }
                className="mt-2 h-11 w-full rounded-xl border border-white/[0.08] bg-[#0D131C] px-4 text-sm text-white outline-none"
              >
                <option value="all">All Sportsbooks</option>

                {sportsbooks.map((book) => (
                  <option key={book} value={book}>
                    {book}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                Market
              </label>

              <select
                value={marketFilter}
                onChange={(event) =>
                  setMarketFilter(event.target.value)
                }
                className="mt-2 h-11 w-full rounded-xl border border-white/[0.08] bg-[#0D131C] px-4 text-sm capitalize text-white outline-none"
              >
                <option value="all">All Markets</option>

                {markets.map((market) => (
                  <option key={market} value={market}>
                    {market}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] pt-4">
            <p className="text-sm text-zinc-500">
              Showing{" "}
              <span className="font-medium text-zinc-200">
                {filteredOpportunities.length}
              </span>{" "}
              of {opportunities.length} opportunities
            </p>

            {(sportsbookFilter !== "all" ||
              marketFilter !== "all" ||
              sortBy !== "rank") && (
              <button
                onClick={() => {
                  setSortBy("rank");
                  setSportsbookFilter("all");
                  setMarketFilter("all");
                }}
                className="text-sm text-zinc-600 transition hover:text-white"
              >
                Reset filters
              </button>
            )}
          </div>
        </section>

        <div className="mt-8 flex flex-wrap items-center gap-8 border-y border-white/[0.07] py-5">
          <div>
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Results
            </p>

            <p className="mt-1 text-xl font-semibold">
              {filteredOpportunities.length}
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
          {filteredOpportunities.map((opportunity) => {
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
                      {opportunity.book} •{" "}
                      {opportunity.price > 0 ? "+" : ""}
                      {opportunity.price}
                    </p>

                    <div className="mt-5 grid gap-3 sm:grid-cols-3">
                      <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                        <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                          Model Prob
                        </p>
                        <p className="mt-2 font-semibold">
                          {opportunity.modelProbability.toFixed(1)}%
                        </p>
                      </div>

                      <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                        <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                          Market Implied
                        </p>
                        <p className="mt-2 font-semibold">
                          {opportunity.impliedProbability.toFixed(1)}%
                        </p>
                      </div>

                      <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                        <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                          EV / $1
                        </p>
                        <p className="mt-2 font-semibold">
                          +${opportunity.evPerDollar.toFixed(3)}
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
                          Model Edge
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
                      <a
                        href={`/opportunities/${opportunity.id}`}
                        className="flex h-11 w-full items-center justify-center rounded-lg border border-white/10 bg-transparent px-5 text-sm font-medium text-white transition hover:bg-white/[0.05]"
                      >
                        View Full Analysis →
                      </a>

                      <Button
                        onClick={() => addToCard(opportunity)}
                        disabled={isAdded}
                        className={
                          isAdded
                            ? "h-11 w-full bg-emerald-400/10 text-emerald-300"
                            : "h-11 w-full bg-white text-black hover:bg-zinc-200"
                        }
                      >
                        {isAdded ? "Added ✓" : "Add to My Card"}
                      </Button>

                      {isAdded && (
                        <Link
                          href="/my-card"
                          className="flex h-11 w-full items-center justify-center rounded-lg border border-white/10 bg-transparent px-5 text-sm font-medium text-white transition hover:bg-white/[0.05]"
                        >
                          View My Card →
                        </Link>
                      )}
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
        </section>

        {filteredOpportunities.length === 0 && (
          <section className="mt-8 rounded-3xl border border-white/[0.08] bg-[#0D131C] p-8">
            <h2 className="text-2xl font-semibold">
              No opportunities match those filters.
            </h2>

            <p className="mt-3 text-sm text-zinc-500">
              Reset the filters to return to the full model board.
            </p>

            <Button
              onClick={() => {
                setSortBy("rank");
                setSportsbookFilter("all");
                setMarketFilter("all");
              }}
              className="mt-6 bg-white text-black hover:bg-zinc-200"
            >
              Reset Filters
            </Button>
          </section>
        )}
      </div>
    </main>
  );
}