"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

type MarketIntelligence = {
  score: number;
  grade: string;
  signal: string;
  booksTracked: number;
  booksMoving: number;
  steamBooks: number;
  supportingBooks: number;
  opposingBooks: number;
  consensus: number;
  largestPointMove: number;
  largestPriceMove: number;
  marketSupport: boolean;
  snapshots: number;
};

type SportsIntelligenceScore = {
  score: number;
  grade: string;
  stars: number;
  recommendation: string;

  components: {
    modelEdge: number;
    expectedValue: number;
    confidence: number;
    marketIntelligence: number;
    dataCompleteness: number;
  };

  reasons: string[];
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

  marketIntelligence: MarketIntelligence;

  sportsIntelligenceScore: SportsIntelligenceScore;
};

type ApiResponse = {
  count: number;
  source: string;
  opportunities: Opportunity[];
};

function formatStars(stars: number) {
  return {
    filled: "★".repeat(stars),
    empty: "☆".repeat(5 - stars),
  };
}

function scoreTextColor(score: number) {
  if (score >= 90) {
    return "text-emerald-400";
  }

  if (score >= 80) {
    return "text-sky-400";
  }

  if (score >= 70) {
    return "text-amber-400";
  }

  return "text-zinc-400";
}

export default function Home() {
  const [opportunities, setOpportunities] =
    useState<Opportunity[]>([]);

  const [loading, setLoading] =
    useState(true);

  const [error, setError] =
    useState("");

  useEffect(() => {
    async function loadData() {
      try {
        setLoading(true);
        setError("");

        const response = await fetch(
          "http://localhost:8000/api/opportunities?limit=100"
        );

        if (!response.ok) {
          throw new Error(
            "Failed to load opportunities"
          );
        }

        const data: ApiResponse =
          await response.json();

        setOpportunities(
          data.opportunities
        );
      } catch (err) {
        console.error(err);

        setError(
          "Unable to load live model data."
        );
      } finally {
        setLoading(false);
      }
    }

    loadData();
  }, []);

  const rankedBySportsScore =
    useMemo(() => {
      return [...opportunities].sort(
        (a, b) =>
          b.sportsIntelligenceScore
            .score -
          a.sportsIntelligenceScore
            .score
      );
    }, [opportunities]);

  const topOpportunity =
    rankedBySportsScore[0];

  const topThree =
    rankedBySportsScore.slice(
      1,
      4
    );

  const strongestEdge =
    opportunities.length > 0
      ? Math.max(
          ...opportunities.map(
            (item) => item.edge
          )
        )
      : 0;

  const highestConfidence =
    opportunities.length > 0
      ? Math.max(
          ...opportunities.map(
            (item) =>
              item.confidence
          )
        )
      : 0;

  const highestSportsScore =
    opportunities.length > 0
      ? Math.max(
          ...opportunities.map(
            (item) =>
              item
                .sportsIntelligenceScore
                .score
          )
        )
      : 0;

  const strongBets =
    opportunities.filter(
      (item) =>
        item
          .sportsIntelligenceScore
          .score >= 80
    );

  const marketConfirmed =
    opportunities.filter(
      (item) =>
        item.marketIntelligence
          .marketSupport
    );

  const steamOpportunities =
    opportunities.filter(
      (item) =>
        item.marketIntelligence
          .steamBooks > 0
    );

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
          <p className="text-red-400">
            {error}
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">

      {/* HEADER */}

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

          <div className="flex items-center gap-3">

            <Badge
              variant="outline"
              className="border-white/[0.08] bg-white/[0.03] text-zinc-400"
            >
              {opportunities.length} Opportunities
            </Badge>

            <Badge
              variant="outline"
              className="border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-400"
            >
              Model Live
            </Badge>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-[1320px] px-6 py-10 lg:px-10">

        {/* INTRO */}

        <section>
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-zinc-600">
            Today&apos;s Intelligence
          </p>

          <div className="mt-3 flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">

            <div>
              <h2 className="max-w-4xl text-4xl font-semibold tracking-[-0.03em] md:text-5xl">
                Your NFL decision engine is live.
              </h2>

              <p className="mt-4 max-w-2xl text-base leading-7 text-zinc-500">
                Sports Intelligence combines model edge,
                expected value, confidence, market behavior,
                and data quality into one unified decision score.
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

                <Link href="/line-movement">
                  <Button
                    variant="outline"
                    className="h-11 border-white/10 bg-transparent px-5 text-white hover:bg-white/[0.05]"
                  >
                    Line Movement
                  </Button>
                </Link>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-x-10 gap-y-5 sm:grid-cols-4">

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
                  Market Support
                </p>

                <p className="mt-1 text-xl font-semibold">
                  {marketConfirmed.length}
                </p>
              </div>

              <div>
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Steam Signals
                </p>

                <p className="mt-1 text-xl font-semibold">
                  {steamOpportunities.length}
                </p>
              </div>

              <div>
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Best SI Score
                </p>

                <p className="mt-1 text-xl font-semibold text-emerald-400">
                  {highestSportsScore.toFixed(1)}
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* KPI STRIP */}

        <section className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">

          <div className="rounded-2xl border border-white/[0.07] bg-[#0B1119] p-5">
            <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-700">
              Ranked Opportunities
            </p>

            <p className="mt-2 text-3xl font-semibold">
              {opportunities.length}
            </p>
          </div>

          <div className="rounded-2xl border border-white/[0.07] bg-[#0B1119] p-5">
            <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-700">
              Strongest Edge
            </p>

            <p className="mt-2 text-3xl font-semibold text-emerald-400">
              +{strongestEdge.toFixed(1)}%
            </p>
          </div>

          <div className="rounded-2xl border border-white/[0.07] bg-[#0B1119] p-5">
            <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-700">
              Highest Confidence
            </p>

            <p className="mt-2 text-3xl font-semibold">
              {highestConfidence}
            </p>
          </div>

          <div className="rounded-2xl border border-white/[0.07] bg-[#0B1119] p-5">
            <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-700">
              Market Confirmed
            </p>

            <p className="mt-2 text-3xl font-semibold">
              {marketConfirmed.length}
            </p>
          </div>
        </section>

        {/* TOP OPPORTUNITY */}

        {topOpportunity && (() => {
          const score =
            topOpportunity.sportsIntelligenceScore;

          const market =
            topOpportunity.marketIntelligence;

          const stars =
            formatStars(score.stars);

          const scoreColor =
            scoreTextColor(score.score);

          return (
            <section className="mt-8 overflow-hidden rounded-3xl border border-white/[0.08] bg-[linear-gradient(135deg,#121823_0%,#0D121A_100%)] shadow-2xl shadow-black/30">

              <div className="grid lg:grid-cols-[1.35fr_0.65fr]">

                {/* LEFT */}

                <div className="p-8 lg:p-10">

                  <div className="flex flex-wrap items-center gap-3">

                    <Badge className="bg-emerald-400 text-black hover:bg-emerald-400">
                      Top SI Opportunity
                    </Badge>

                    <Badge
                      variant="outline"
                      className="border-white/[0.08] bg-white/[0.03] text-zinc-300"
                    >
                      Grade {score.grade}
                    </Badge>

                    <Badge
                      variant="outline"
                      className="border-white/[0.08] bg-white/[0.03] text-zinc-400"
                    >
                      Market {market.grade}
                    </Badge>
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

                  <div className="mt-6 flex flex-wrap items-center gap-5">

                    <div>
                      <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-700">
                        Sports Intelligence Score
                      </p>

                      <div className="mt-2 flex items-baseline gap-2">
                        <span
                          className={`text-5xl font-semibold ${scoreColor}`}
                        >
                          {score.score.toFixed(1)}
                        </span>

                        <span className="text-sm text-zinc-600">
                          /100
                        </span>
                      </div>
                    </div>

                    <div>
                      <p
                        className={`text-3xl font-semibold ${scoreColor}`}
                      >
                        {score.grade}
                      </p>

                      <p className="mt-1 tracking-[0.12em] text-amber-400">
                        {stars.filled}
                        <span className="text-zinc-700">
                          {stars.empty}
                        </span>
                      </p>
                    </div>

                    <div>
                      <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-700">
                        Recommendation
                      </p>

                      <p className="mt-2 text-lg font-semibold">
                        {score.recommendation}
                      </p>
                    </div>
                  </div>

                  <p className="mt-6 max-w-2xl text-base leading-7 text-zinc-400">
                    Model probability is{" "}
                    {topOpportunity.modelProbability.toFixed(1)}%
                    versus a market-implied probability of{" "}
                    {topOpportunity.impliedProbability.toFixed(1)}%,
                    creating a current edge of +
                    {topOpportunity.edge.toFixed(1)}%.
                  </p>

                  <div className="mt-6 space-y-2">

                    {score.reasons
                      .slice(0, 4)
                      .map((reason) => (
                        <p
                          key={reason}
                          className="text-sm text-zinc-400"
                        >
                          <span className="mr-2 text-emerald-400">
                            ✓
                          </span>

                          {reason}
                        </p>
                      ))}
                  </div>

                  <div className="mt-8 flex flex-wrap gap-3">

                    <Link
                      href={`/opportunities/${topOpportunity.id}`}
                    >
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

                {/* RIGHT */}

                <div className="border-t border-white/[0.07] bg-black/10 p-8 lg:border-l lg:border-t-0 lg:p-10">

                  <p className="text-xs uppercase tracking-[0.18em] text-zinc-600">
                    Decision Snapshot
                  </p>

                  <div className="mt-7 space-y-6">

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
                        Expected Value
                      </span>

                      <span className="text-2xl font-semibold">
                        +${topOpportunity.evPerDollar.toFixed(3)}
                      </span>
                    </div>

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
                        Market Score
                      </span>

                      <span className="text-2xl font-semibold">
                        {market.score.toFixed(1)}
                        <span className="text-sm text-zinc-600">
                          /10
                        </span>
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
          );
        })()}

        {/* NEXT BEST OPPORTUNITIES */}

        <section className="mt-10">

          <div className="flex items-end justify-between gap-4">

            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-zinc-700">
                Next Best Opportunities
              </p>

              <h3 className="mt-2 text-2xl font-semibold">
                Highest Sports Intelligence Scores.
              </h3>
            </div>

            <Link
              href="/opportunities"
              className="text-sm text-zinc-500 transition hover:text-white"
            >
              Full Board →
            </Link>
          </div>

          <div className="mt-5 grid gap-4 lg:grid-cols-3">

            {topThree.map((opportunity) => {
              const score =
                opportunity.sportsIntelligenceScore;

              const stars =
                formatStars(score.stars);

              return (
                <Link
                  key={opportunity.id}
                  href={`/opportunities/${opportunity.id}`}
                  className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6 transition hover:border-white/15 hover:bg-[#101721]"
                >
                  <div className="flex items-start justify-between gap-4">

                    <div>
                      <span className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                        SI Score
                      </span>

                      <p
                        className={`mt-1 text-3xl font-semibold ${scoreTextColor(
                          score.score
                        )}`}
                      >
                        {score.score.toFixed(1)}
                      </p>
                    </div>

                    <div className="text-right">

                      <p className="text-xl font-semibold">
                        {score.grade}
                      </p>

                      <p className="mt-1 text-xs tracking-[0.08em] text-amber-400">
                        {stars.filled}
                        <span className="text-zinc-700">
                          {stars.empty}
                        </span>
                      </p>
                    </div>
                  </div>

                  <p className="mt-6 text-sm text-zinc-500">
                    {opportunity.matchup}
                  </p>

                  <h3 className="mt-1 text-2xl font-semibold">
                    {opportunity.pick}
                  </h3>

                  <p className="mt-2 text-sm text-zinc-600">
                    {opportunity.book} •{" "}
                    {score.recommendation}
                  </p>

                  <div className="mt-5 grid grid-cols-2 gap-3">

                    <div className="rounded-xl border border-white/[0.06] bg-black/10 p-3">
                      <p className="text-[9px] uppercase tracking-wider text-zinc-700">
                        Edge
                      </p>

                      <p className="mt-2 font-semibold text-emerald-400">
                        +{opportunity.edge.toFixed(1)}%
                      </p>
                    </div>

                    <div className="rounded-xl border border-white/[0.06] bg-black/10 p-3">
                      <p className="text-[9px] uppercase tracking-wider text-zinc-700">
                        Market
                      </p>

                      <p className="mt-2 font-semibold">
                        {opportunity.marketIntelligence.score.toFixed(1)}
                        /10
                      </p>
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
        </section>

        {/* COMMAND CENTER */}

        <section className="mt-10">

          <p className="text-xs uppercase tracking-[0.18em] text-zinc-700">
            Command Center
          </p>

          <h3 className="mt-2 text-2xl font-semibold">
            Explore the intelligence platform.
          </h3>

          <div className="mt-5 grid gap-4 md:grid-cols-2 lg:grid-cols-4">

            <Link
              href="/opportunities"
              className="rounded-2xl border border-white/[0.07] bg-[#0B1119] p-6 transition hover:border-white/15"
            >
              <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                Opportunities
              </p>

              <p className="mt-3 text-2xl font-semibold">
                {opportunities.length} positions
              </p>

              <p className="mt-2 text-sm leading-6 text-zinc-500">
                Review the complete board ranked by model and SI score.
              </p>
            </Link>

            <Link
              href="/line-movement"
              className="rounded-2xl border border-white/[0.07] bg-[#0B1119] p-6 transition hover:border-white/15"
            >
              <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                Market Movement
              </p>

              <p className="mt-3 text-2xl font-semibold">
                {steamOpportunities.length} steam signals
              </p>

              <p className="mt-2 text-sm leading-6 text-zinc-500">
                Monitor sportsbook movement, steam, and directional agreement.
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
                Portfolio
              </p>

              <p className="mt-2 text-sm leading-6 text-zinc-500">
                Review saved positions, exposure, EV, and model confidence.
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

              <p className="mt-2 text-sm leading-6 text-zinc-500">
                Distilled information affecting current betting decisions.
              </p>
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}