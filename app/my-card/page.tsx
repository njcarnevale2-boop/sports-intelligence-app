"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

type SavedBet = {
  id?: string;
  matchup: string;
  pick: string;
  book: string;
  confidence?: number;
  edge: number | string;
  evPerDollar?: number;
  kelly20?: number;
};

type PortfolioBet = {
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
  rawUnits: number;
  recommendedUnits: number;
};

type PortfolioResponse = {
  count: number;
  source: string;
  summary: {
    totalRecommendedUnits: number;
    averageEdge: number;
    averageModelProbability: number;
    expectedValueUnits: number;
  };
  portfolio: PortfolioBet[];
};

export default function MyCardPage() {
  const [savedBets, setSavedBets] = useState<SavedBet[]>([]);
  const [portfolio, setPortfolio] = useState<PortfolioBet[]>([]);
  const [portfolioSummary, setPortfolioSummary] =
    useState<PortfolioResponse["summary"] | null>(null);

  const [loadingPortfolio, setLoadingPortfolio] = useState(true);
  const [portfolioError, setPortfolioError] = useState("");

  useEffect(() => {
    const saved = localStorage.getItem("sports-intelligence-card");

    if (!saved) return;

    try {
      setSavedBets(JSON.parse(saved));
    } catch (err) {
      console.error("Unable to read saved card:", err);
    }
  }, []);

  useEffect(() => {
    async function loadPortfolio() {
      try {
        const response = await fetch(
          "http://localhost:8000/api/portfolio"
        );

        if (!response.ok) {
          throw new Error("Failed to load portfolio");
        }

        const data: PortfolioResponse = await response.json();

        setPortfolio(data.portfolio);
        setPortfolioSummary(data.summary);
      } catch (err) {
        console.error(err);
        setPortfolioError("Unable to load model portfolio.");
      } finally {
        setLoadingPortfolio(false);
      }
    }

    loadPortfolio();
  }, []);

  function removeBet(indexToRemove: number) {
    const updatedBets = savedBets.filter(
      (_, index) => index !== indexToRemove
    );

    setSavedBets(updatedBets);

    localStorage.setItem(
      "sports-intelligence-card",
      JSON.stringify(updatedBets)
    );
  }

  function clearCard() {
    setSavedBets([]);
    localStorage.removeItem("sports-intelligence-card");
  }

  const savedAverageEdge = useMemo(() => {
    if (savedBets.length === 0) return 0;

    const total = savedBets.reduce((sum, bet) => {
      const edge =
        typeof bet.edge === "number"
          ? bet.edge
          : Number.parseFloat(
              bet.edge.replace("%", "").replace("+", "")
            );

      return sum + (Number.isFinite(edge) ? edge : 0);
    }, 0);

    return total / savedBets.length;
  }, [savedBets]);

  const savedAverageConfidence = useMemo(() => {
    const betsWithConfidence = savedBets.filter(
      (bet) => typeof bet.confidence === "number"
    );

    if (betsWithConfidence.length === 0) return 0;

    return (
      betsWithConfidence.reduce(
        (sum, bet) => sum + (bet.confidence ?? 0),
        0
      ) / betsWithConfidence.length
    );
  }, [savedBets]);

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-6xl px-6 py-10 lg:px-10">

        <section>
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-zinc-600">
            Portfolio Intelligence
          </p>

          <div className="mt-4 flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
            <div>
              <h1 className="text-4xl font-semibold tracking-[-0.03em] md:text-6xl">
                My Card
              </h1>

              <p className="mt-4 max-w-3xl text-base leading-7 text-zinc-500">
                Compare your manually selected positions with the portfolio
                currently recommended by NFL Analytics OS.
              </p>
            </div>

            <Link href="/opportunities">
              <Button
                variant="outline"
                className="border-white/10 bg-transparent text-white hover:bg-white/[0.05]"
              >
                Add Opportunities →
              </Button>
            </Link>
          </div>
        </section>

        <section className="mt-10">
          <div className="flex items-end justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-700">
                Your Saved Card
              </p>

              <h2 className="mt-2 text-2xl font-semibold">
                Positions you selected manually.
              </h2>
            </div>

            {savedBets.length > 0 && (
              <button
                onClick={clearCard}
                className="text-sm text-zinc-600 transition hover:text-red-400"
              >
                Clear Card
              </button>
            )}
          </div>

          {savedBets.length === 0 ? (
            <div className="mt-5 rounded-3xl border border-white/[0.08] bg-[#0D131C] p-8">
              <p className="text-sm text-zinc-500">
                Your saved card is empty.
              </p>

              <Link href="/opportunities">
                <Button className="mt-5 bg-white text-black hover:bg-zinc-200">
                  Browse Opportunities →
                </Button>
              </Link>
            </div>
          ) : (
            <>
              <div className="mt-5 grid gap-4 md:grid-cols-3">
                <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                    Saved Selections
                  </p>
                  <p className="mt-3 text-3xl font-semibold">
                    {savedBets.length}
                  </p>
                </div>

                <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                    Avg Confidence
                  </p>
                  <p className="mt-3 text-3xl font-semibold">
                    {savedAverageConfidence.toFixed(1)}
                  </p>
                </div>

                <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                    Avg Edge
                  </p>
                  <p className="mt-3 text-3xl font-semibold text-emerald-400">
                    +{savedAverageEdge.toFixed(1)}%
                  </p>
                </div>
              </div>

              <div className="mt-5 space-y-4">
                {savedBets.map((bet, index) => (
                  <article
                    key={`${bet.id ?? bet.pick}-${index}`}
                    className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7"
                  >
                    <div className="flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
                      <div>
                        <p className="text-sm text-zinc-500">
                          {bet.matchup}
                        </p>

                        <h3 className="mt-1 text-3xl font-semibold">
                          {bet.pick}
                        </h3>

                        <p className="mt-2 text-sm text-zinc-600">
                          {bet.book}
                        </p>
                      </div>

                      <div className="flex flex-wrap gap-3">
                        {typeof bet.confidence === "number" && (
                          <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                            <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                              Confidence
                            </p>
                            <p className="mt-2 font-semibold">
                              {bet.confidence}
                            </p>
                          </div>
                        )}

                        <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                          <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                            Edge
                          </p>
                          <p className="mt-2 font-semibold text-emerald-400">
                            {typeof bet.edge === "number"
                              ? `+${bet.edge.toFixed(1)}%`
                              : bet.edge}
                          </p>
                        </div>

                        <button
                          onClick={() => removeBet(index)}
                          className="rounded-xl border border-white/[0.07] px-5 py-3 text-sm text-zinc-600 transition hover:border-red-400/20 hover:bg-red-400/[0.04] hover:text-red-400"
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
        </section>

        <section className="mt-14 border-t border-white/[0.07] pt-10">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-400">
                Model Portfolio
              </p>

              <h2 className="mt-2 text-3xl font-semibold">
                Recommended allocation from the model.
              </h2>

              <p className="mt-3 max-w-2xl text-sm leading-7 text-zinc-500">
                This section comes directly from the current portfolio
                recommendations output and is separate from your manually saved
                selections.
              </p>
            </div>

            <Badge
              variant="outline"
              className="border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-400"
            >
              Live Model Allocation
            </Badge>
          </div>

          {loadingPortfolio && (
            <div className="mt-6 rounded-3xl border border-white/[0.08] bg-[#0D131C] p-8">
              <p className="text-sm text-zinc-500">
                Loading model portfolio...
              </p>
            </div>
          )}

          {portfolioError && (
            <div className="mt-6 rounded-3xl border border-red-400/15 bg-red-400/[0.03] p-8">
              <p className="text-sm text-red-400">
                {portfolioError}
              </p>
            </div>
          )}

          {!loadingPortfolio &&
            !portfolioError &&
            portfolioSummary && (
              <>
                <div className="mt-6 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
                  <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
                    <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                      Positions
                    </p>
                    <p className="mt-3 text-3xl font-semibold">
                      {portfolio.length}
                    </p>
                  </div>

                  <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
                    <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                      Recommended Units
                    </p>
                    <p className="mt-3 text-3xl font-semibold">
                      {portfolioSummary.totalRecommendedUnits.toFixed(2)}
                    </p>
                  </div>

                  <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
                    <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                      Avg Edge
                    </p>
                    <p className="mt-3 text-3xl font-semibold text-emerald-400">
                      +{portfolioSummary.averageEdge.toFixed(1)}%
                    </p>
                  </div>

                  <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
                    <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                      Expected Value
                    </p>
                    <p className="mt-3 text-3xl font-semibold text-emerald-400">
                      +{portfolioSummary.expectedValueUnits.toFixed(3)} units
                    </p>
                  </div>
                </div>

                <div className="mt-6 space-y-4">
                  {portfolio.map((bet, index) => (
                    <article
                      key={bet.id}
                      className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7"
                    >
                      <div className="flex flex-col gap-7 lg:flex-row lg:items-center lg:justify-between">
                        <div>
                          <div className="flex items-center gap-3">
                            <span className="text-xs text-zinc-700">
                              0{index + 1}
                            </span>

                            <Badge
                              variant="outline"
                              className="border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-400"
                            >
                              {bet.recommendation}
                            </Badge>
                          </div>

                          <p className="mt-5 text-sm text-zinc-500">
                            {bet.matchup}
                          </p>

                          <h3 className="mt-1 text-3xl font-semibold">
                            {bet.pick}
                          </h3>

                          <p className="mt-2 text-sm text-zinc-600">
                            {bet.book} •{" "}
                            {bet.price > 0 ? "+" : ""}
                            {bet.price}
                          </p>
                        </div>

                        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                          <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                            <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                              Units
                            </p>
                            <p className="mt-2 text-lg font-semibold">
                              {bet.recommendedUnits.toFixed(2)}
                            </p>
                          </div>

                          <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                            <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                              Edge
                            </p>
                            <p className="mt-2 text-lg font-semibold text-emerald-400">
                              +{bet.edge.toFixed(1)}%
                            </p>
                          </div>

                          <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                            <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                              Model Prob
                            </p>
                            <p className="mt-2 text-lg font-semibold">
                              {bet.modelProbability.toFixed(1)}%
                            </p>
                          </div>

                          <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                            <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                              EV / $1
                            </p>
                            <p className="mt-2 text-lg font-semibold">
                              +${bet.evPerDollar.toFixed(3)}
                            </p>
                          </div>
                        </div>
                      </div>
                    </article>
                  ))}
                </div>

                <section className="mt-6 rounded-3xl border border-emerald-400/15 bg-emerald-400/[0.035] p-8">
                  <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-400">
                    Portfolio Summary
                  </p>

                  <h3 className="mt-3 text-2xl font-semibold">
                    {portfolioSummary.totalRecommendedUnits.toFixed(2)} units
                    across {portfolio.length} model-selected positions.
                  </h3>

                  <p className="mt-4 max-w-3xl text-sm leading-7 text-zinc-400">
                    Average model probability is{" "}
                    {portfolioSummary.averageModelProbability.toFixed(1)}%,
                    average edge is +
                    {portfolioSummary.averageEdge.toFixed(1)}%, and the current
                    portfolio produces an estimated +
                    {portfolioSummary.expectedValueUnits.toFixed(3)} units of
                    expected value under the model assumptions.
                  </p>
                </section>
              </>
            )}
        </section>
      </div>
    </main>
  );
}