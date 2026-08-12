"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import ExecutiveSummary from "@/components/executive-summary";
import SportsIntelligenceScoreCard from "@/components/sports-intelligence-score-card";
import { fetchJson } from "../../lib/api";
import { trackAnalyticsEvent } from "../../lib/analytics";
import { addToCard as addToCardWithSnapshot } from "@/lib/add-to-card";

type AlternateBook = {
  book: string;
  point: number;
  price: number;
  edge: number;
  evPerDollar: number;
};

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

  weights: {
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

  alternateBooks?: AlternateBook[];
};

type DecisionTimeline = {
  timeline: Array<{
    timestamp: string;
    category: string;
    oldValue: unknown;
    newValue: unknown;
    impact: string;
    reason: string;
  }>;
  latestSummary: string;
  biggestChange: {
    timestamp: string;
    category: string;
    oldValue: unknown;
    newValue: unknown;
    impact: string;
    reason: string;
  } | null;
  recommendationChanged: boolean;
  scoreHistory: Array<{ timestamp: string; score: unknown }>;
  changeCount: number;
};

type GameProjection = {
  eventId: string;
  commenceTime: string;
  matchup: string;
  awayTeam: string;
  homeTeam: string;

  teamPower: {
    away: number;
    home: number;
    differenceHomeMinusAway: number;
  };

  model: {
    marginHome: number;
    total: number;

    projectedScore: {
      away: number;
      home: number;
    };
  };

  market: {
    marginHome: number;
    homeSpread: number;
    total: number;
  };

  spreadAnalysis: {
    edgePoints: number;
    homeCoverProbability: number;
    homeCoverFairOdds: number;
  };
};

type ScheduleContext = {
  eventId: string;
  gameId: string;
  season: number;
  week: number;
  gameday: string;
  matchup: string;
  awayTeam: string;
  homeTeam: string;

  rest: {
    homeDays: number | null;
    awayDays: number | null;
    advantageHomeDays: number | null;
    label: string;
    weekOneNeutralized: boolean;
    shortRestHome: boolean;
    shortRestAway: boolean;
    longRestHome: boolean;
    longRestAway: boolean;
  };

  travel: {
    awayMiles: number | null;
    awayTimezoneShiftHours: number | null;
  };
};

function formatOdds(price: number) {
  return price > 0
    ? `+${price}`
    : `${price}`;
}

function formatSignedNumber(value: number) {
  if (value > 0) {
    return `+${value}`;
  }

  return `${value}`;
}

function formatPoint(
  market: string,
  side: string,
  point: number
) {
  if (market === "spread") {
    return point > 0
      ? `+${point}`
      : `${point}`;
  }

  if (market === "total") {
    return `${side.toUpperCase()} ${point}`;
  }

  return `${point}`;
}

function marketAppearance(score: number) {
  if (score >= 8) {
    return {
      text: "text-emerald-400",
      border:
        "border-emerald-400/20 bg-emerald-400/[0.04]",
    };
  }

  if (score >= 6) {
    return {
      text: "text-sky-400",
      border:
        "border-sky-400/20 bg-sky-400/[0.04]",
    };
  }

  if (score >= 4) {
    return {
      text: "text-amber-400",
      border:
        "border-amber-400/20 bg-amber-400/[0.04]",
    };
  }

  return {
    text: "text-zinc-500",
    border:
      "border-white/[0.07] bg-black/10",
  };
}

export default function OpportunityAnalysisPage() {
  const params =
    useParams<{ id: string }>();

  const [
    opportunity,
    setOpportunity,
  ] = useState<Opportunity | null>(
    null
  );

  const [
    projection,
    setProjection,
  ] = useState<GameProjection | null>(
    null
  );

  const [
    context,
    setContext,
  ] = useState<ScheduleContext | null>(
    null
  );

  const [loading, setLoading] =
    useState(true);

  const [
    projectionError,
    setProjectionError,
  ] = useState("");

  const [
    contextError,
    setContextError,
  ] = useState("");

  const [error, setError] =
    useState("");

  const [executiveAnalysis, setExecutiveAnalysis] =
    useState<{
      headline: string;
      recommendation: string;
      summary: string;
      strengths: string[];
      risks: string[];
      watchItems: string[];
      stakeRecommendation: string;
      bestPriceSummary: string;
    } | null>(null);

  const [explainability, setExplainability] = useState<{
    overallSummary: string;
    strengths: string[];
    weaknesses: string[];
    confidenceExplanation: string;
    marketExplanation: string;
    injuryExplanation: string;
    weatherExplanation: string;
    keyReasons: string[];
    whatCouldImprove: string[];
    riskFactors: string[];
  } | null>(null);

  const [decisionTimeline, setDecisionTimeline] = useState<DecisionTimeline | null>(null);

  const [added, setAdded] = useState(false);
  const [snapshotError, setSnapshotError] = useState("");

  useEffect(() => {
    async function loadData() {
      try {
        setLoading(true);
        setError("");

        void trackAnalyticsEvent("OpportunityViewed", {
          page: "opportunity-detail",
          opportunityId: params.id,
        });

        const opportunityData = await fetchJson<Opportunity>(
          `/api/opportunities/${params.id}`
        );

        setOpportunity(
          opportunityData
        );

        const saved =
          localStorage.getItem(
            "sports-intelligence-card"
          );

        if (saved) {
          try {
            const card: Opportunity[] =
              JSON.parse(saved);

            setAdded(
              card.some(
                (bet) =>
                  bet.id ===
                  opportunityData.id
              )
            );
          } catch {
            setAdded(false);
          }
        }

        try {
          const analysisData = await fetchJson<{
            executiveAnalysis: {
              headline: string;
              recommendation: string;
              summary: string;
              strengths: string[];
              risks: string[];
              watchItems: string[];
              stakeRecommendation: string;
              bestPriceSummary: string;
            };
            explainability: {
              overallSummary: string;
              strengths: string[];
              weaknesses: string[];
              confidenceExplanation: string;
              marketExplanation: string;
              injuryExplanation: string;
              weatherExplanation: string;
              keyReasons: string[];
              whatCouldImprove: string[];
              riskFactors: string[];
            };
            decisionTimeline: DecisionTimeline;
          }>(`/api/opportunities/${opportunityData.id}/analysis`);
          setExecutiveAnalysis(analysisData.executiveAnalysis);
          setExplainability(analysisData.explainability);
          setDecisionTimeline(analysisData.decisionTimeline);
        } catch {
          setExecutiveAnalysis(null);
          setExplainability(null);
        }

        try {
          const timelineData = await fetchJson<DecisionTimeline>(
            `/api/opportunities/${opportunityData.id}/timeline`
          );
          setDecisionTimeline(timelineData);
        } catch {
          setDecisionTimeline(null);
        }

        const [
          projectionResult,
          contextResult,
        ] =
          await Promise.allSettled([
            fetchJson<GameProjection>(`/api/games/${opportunityData.eventId}`),

            fetchJson<ScheduleContext>(`/api/games/${opportunityData.eventId}/context`),
          ]);

        if (
          projectionResult.status ===
          "fulfilled"
        ) {
          setProjection(
            projectionResult.value as GameProjection
          );
        } else {
          setProjectionError(
            "Game projection is currently unavailable."
          );
        }

        if (
          contextResult.status ===
          "fulfilled"
        ) {
          setContext(
            contextResult.value as ScheduleContext
          );
        } else {
          setContextError(
            "Schedule context is currently unavailable."
          );
        }
      } catch (err) {
        console.error(err);

        setError(
          "Unable to load this opportunity."
        );
      } finally {
        setLoading(false);
      }
    }

    if (params.id) {
      loadData();
    }
  }, [params.id]);

  async function addToCard() {
    if (!opportunity) return;

    setSnapshotError("");
    const result = await addToCardWithSnapshot(opportunity as Record<string, unknown>);
    if (result.success) {
      setAdded(true);
    } else {
      // Card may still be saved locally; surface the CLV tracking failure
      setAdded(true);
      setSnapshotError(result.error);
    }
  }

  if (loading) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:px-10">
          <p className="text-sm text-zinc-500">
            Loading executive
            analysis...
          </p>
        </div>
      </main>
    );
  }

  if (
    error ||
    !opportunity
  ) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:px-10">
          <p className="text-red-400">
            {error ||
              "Opportunity not found."}
          </p>
        </div>
      </main>
    );
  }

  const probabilityGap =
    opportunity.modelProbability -
    opportunity.impliedProbability;

  const alternateBooks =
    opportunity.alternateBooks ??
    [];

  const market =
    opportunity.marketIntelligence;

  const sportsScore =
    opportunity.sportsIntelligenceScore;

  const marketStyle =
    marketAppearance(
      market.score
    );

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-6xl px-6 py-10 lg:px-10">

        {/* TOP NAV */}

        <div className="flex flex-wrap items-center justify-between gap-4">
          <Link
            href="/opportunities"
            className="text-sm text-zinc-500 transition hover:text-white"
          >
            ← Opportunities
          </Link>

          <div className="flex flex-wrap items-center gap-3">

            <span className="text-xs text-zinc-600">
              Model Rank #
              {opportunity.rank}
            </span>

            <Badge
              variant="outline"
              className="border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-400"
            >
              {
                opportunity.recommendation
              }
            </Badge>

            <Badge
              variant="outline"
              className="border-white/[0.08] bg-white/[0.03] text-zinc-300"
            >
              SI {sportsScore.grade}
            </Badge>

            <Badge
              variant="outline"
              className={`${marketStyle.border} ${marketStyle.text}`}
            >
              Market {market.grade}
            </Badge>
          </div>
        </div>

        {/* HERO */}

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
                  {
                    opportunity.book
                  }
                </span>

                <span className="text-sm text-zinc-600">
                  {formatOdds(
                    opportunity.price
                  )}
                </span>
              </div>
            </div>

            <div className="flex flex-wrap gap-10">

              <div>
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  SI Score
                </p>

                <p className="mt-1 text-3xl font-semibold text-emerald-400">
                  {sportsScore.score.toFixed(
                    1
                  )}
                  <span className="text-sm text-zinc-600">
                    /100
                  </span>
                </p>
              </div>

              <div>
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Confidence
                </p>

                <p className="mt-1 text-3xl font-semibold">
                  {
                    opportunity.confidence
                  }
                </p>
              </div>

              <div>
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Model Edge
                </p>

                <p className="mt-1 text-3xl font-semibold text-emerald-400">
                  +
                  {opportunity.edge.toFixed(
                    1
                  )}
                  %
                </p>
              </div>

              <div>
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  EV / $1
                </p>

                <p className="mt-1 text-3xl font-semibold">
                  +$
                  {opportunity.evPerDollar.toFixed(
                    3
                  )}
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* SPORTS INTELLIGENCE SCORE */}

        <section className="mt-10">

          <SportsIntelligenceScoreCard
            score={sportsScore}
          />

          {explainability && (
            <div className="mt-6 rounded-3xl border border-white/[0.08] bg-[#0B1119] p-8">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600">Explainability Engine</p>
                  <h3 className="mt-2 text-2xl font-semibold tracking-tight">How the score is built</h3>
                </div>
                <div className="rounded-full border border-emerald-400/20 bg-emerald-400/[0.05] px-3 py-1 text-sm text-emerald-400">
                  Deterministic rules-based explanation
                </div>
              </div>

              <p className="mt-5 max-w-3xl text-sm leading-7 text-zinc-400">{explainability.overallSummary}</p>

              <div className="mt-8 grid gap-6 lg:grid-cols-2">
                <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">Strengths</p>
                  <ul className="mt-4 space-y-2 text-sm text-zinc-400">
                    {explainability.strengths.map((item) => (
                      <li key={item}>• {item}</li>
                    ))}
                  </ul>
                </div>

                <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">Weaknesses</p>
                  <ul className="mt-4 space-y-2 text-sm text-zinc-400">
                    {explainability.weaknesses.map((item) => (
                      <li key={item}>• {item}</li>
                    ))}
                  </ul>
                </div>
              </div>

              <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">Confidence</p>
                  <p className="mt-3 text-sm leading-7 text-zinc-400">{explainability.confidenceExplanation}</p>
                </div>
                <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">Market</p>
                  <p className="mt-3 text-sm leading-7 text-zinc-400">{explainability.marketExplanation}</p>
                </div>
                <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">Injury</p>
                  <p className="mt-3 text-sm leading-7 text-zinc-400">{explainability.injuryExplanation}</p>
                </div>
                <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">Weather</p>
                  <p className="mt-3 text-sm leading-7 text-zinc-400">{explainability.weatherExplanation}</p>
                </div>
              </div>

              <div className="mt-6 grid gap-4 lg:grid-cols-3">
                <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">Key reasons</p>
                  <ul className="mt-4 space-y-2 text-sm text-zinc-400">
                    {explainability.keyReasons.map((item) => (
                      <li key={item}>• {item}</li>
                    ))}
                  </ul>
                </div>
                <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">What could improve</p>
                  <ul className="mt-4 space-y-2 text-sm text-zinc-400">
                    {explainability.whatCouldImprove.map((item) => (
                      <li key={item}>• {item}</li>
                    ))}
                  </ul>
                </div>
                <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">Risk factors</p>
                  <ul className="mt-4 space-y-2 text-sm text-zinc-400">
                    {explainability.riskFactors.map((item) => (
                      <li key={item}>• {item}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}

          <div className="mt-4 grid gap-3 md:grid-cols-5">

            <div className="rounded-xl border border-white/[0.07] bg-[#0D131C] p-4">
              <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                Model Edge
              </p>

              <p className="mt-2 text-xl font-semibold">
                {sportsScore.components.modelEdge.toFixed(
                  0
                )}
              </p>

              <p className="mt-1 text-xs text-zinc-600">
                30% weight
              </p>
            </div>

            <div className="rounded-xl border border-white/[0.07] bg-[#0D131C] p-4">
              <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                Expected Value
              </p>

              <p className="mt-2 text-xl font-semibold">
                {sportsScore.components.expectedValue.toFixed(
                  0
                )}
              </p>

              <p className="mt-1 text-xs text-zinc-600">
                20% weight
              </p>
            </div>

            <div className="rounded-xl border border-white/[0.07] bg-[#0D131C] p-4">
              <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                Confidence
              </p>

              <p className="mt-2 text-xl font-semibold">
                {sportsScore.components.confidence.toFixed(
                  0
                )}
              </p>

              <p className="mt-1 text-xs text-zinc-600">
                20% weight
              </p>
            </div>

            <div className="rounded-xl border border-white/[0.07] bg-[#0D131C] p-4">
              <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                Market
              </p>

              <p className="mt-2 text-xl font-semibold">
                {sportsScore.components.marketIntelligence.toFixed(
                  0
                )}
              </p>

              <p className="mt-1 text-xs text-zinc-600">
                20% weight
              </p>
            </div>

            <div className="rounded-xl border border-white/[0.07] bg-[#0D131C] p-4">
              <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                Data Quality
              </p>

              <p className="mt-2 text-xl font-semibold">
                {sportsScore.components.dataCompleteness.toFixed(
                  0
                )}
              </p>

              <p className="mt-1 text-xs text-zinc-600">
                10% weight
              </p>
            </div>
          </div>
        </section>

        {/* EXECUTIVE ANALYST */}

        {executiveAnalysis && (
          <section className="mt-8 rounded-3xl border border-white/[0.08] bg-[#0B1119] p-8 lg:p-10">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-700">
              Executive Analyst
            </p>

            <h2 className="mt-3 text-3xl font-semibold tracking-tight">
              {executiveAnalysis.headline}
            </h2>

            <p className="mt-5 max-w-3xl text-base leading-8 text-zinc-400">
              {executiveAnalysis.summary}
            </p>

            <div className="mt-8 grid gap-6 lg:grid-cols-3">
              <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Strengths
                </p>
                <ul className="mt-4 space-y-3 text-sm text-zinc-400">
                  {executiveAnalysis.strengths.map((item) => (
                    <li key={item}>• {item}</li>
                  ))}
                </ul>
              </div>

              <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Risks
                </p>
                <ul className="mt-4 space-y-3 text-sm text-zinc-400">
                  {executiveAnalysis.risks.map((item) => (
                    <li key={item}>• {item}</li>
                  ))}
                </ul>
              </div>

              <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Watch Items
                </p>
                <ul className="mt-4 space-y-3 text-sm text-zinc-400">
                  {executiveAnalysis.watchItems.map((item) => (
                    <li key={item}>• {item}</li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="mt-8 grid gap-4 rounded-2xl border border-white/[0.07] bg-black/10 p-5 md:grid-cols-2">
              <div>
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Stake Recommendation
                </p>
                <p className="mt-3 text-sm leading-7 text-zinc-400">
                  {executiveAnalysis.stakeRecommendation}
                </p>
              </div>

              <div>
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Best Price Summary
                </p>
                <p className="mt-3 text-sm leading-7 text-zinc-400">
                  {executiveAnalysis.bestPriceSummary}
                </p>
              </div>
            </div>
          </section>
        )}

        {/* DECISION TIMELINE */}

        <section className="mt-8 rounded-3xl border border-white/[0.08] bg-[#0B1119] p-8 lg:p-10">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.18em] text-sky-400">Decision Timeline</p>
              <h2 className="mt-2 text-3xl font-semibold tracking-tight">Every meaningful change that shaped this recommendation</h2>
            </div>
            <div className="rounded-full border border-white/[0.08] bg-white/[0.04] px-3 py-1 text-sm text-zinc-400">
              {decisionTimeline?.changeCount ?? 0} updates
            </div>
          </div>

          {decisionTimeline && decisionTimeline.timeline.length > 0 ? (
            <div className="mt-8 space-y-4">
              {decisionTimeline.timeline.map((entry, index) => (
                <div key={`${entry.timestamp}-${entry.category}-${index}`} className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div>
                      <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-600">{entry.timestamp}</p>
                      <h3 className="mt-2 text-lg font-semibold text-white">{entry.category}</h3>
                      <p className="mt-2 text-sm leading-7 text-zinc-400">{entry.reason}</p>
                    </div>
                    <div className="rounded-2xl border border-white/[0.08] bg-black/20 px-4 py-3 text-sm text-zinc-300">
                      <p>{String(entry.oldValue)} → {String(entry.newValue)}</p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="mt-8 rounded-2xl border border-dashed border-white/[0.1] bg-black/10 p-8 text-center text-sm text-zinc-400">
              No meaningful changes have occurred yet.
            </div>
          )}
        </section>

        {/* EXECUTIVE RECOMMENDATION */}

        <section className="mt-8 rounded-3xl border border-emerald-400/15 bg-[linear-gradient(135deg,#111A18_0%,#0C121A_100%)] p-8 lg:p-10">

          <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-400">
            Executive Recommendation
          </p>

          <h2 className="mt-3 max-w-4xl text-3xl font-semibold tracking-tight">
            {sportsScore.recommendation}. The
            model sees a{" "}
            {probabilityGap.toFixed(
              1
            )}{" "}
            percentage-point probability
            advantage over the market.
          </h2>

          <p className="mt-5 max-w-3xl text-base leading-8 text-zinc-400">
            NFL Analytics OS estimates this
            position at{" "}
            {opportunity.modelProbability.toFixed(
              1
            )}
            % versus a market-implied
            probability of{" "}
            {opportunity.impliedProbability.toFixed(
              1
            )}
            %. The best available price is{" "}
            {opportunity.pick} at{" "}
            {opportunity.book} for{" "}
            {formatOdds(
              opportunity.price
            )}
            .
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
          {snapshotError && (
            <p className="mt-2 text-xs text-amber-400">{snapshotError}</p>
          )}
        </section>

        {/* EXECUTIVE SUMMARY */}

        <div className="mt-8">
          <ExecutiveSummary
            opportunity={
              opportunity
            }
            projection={
              projection
            }
            context={context}
          />
        </div>

        {/* MATCHUP PROJECTION */}

        <section className="mt-8">

          <p className="text-xs font-medium uppercase tracking-[0.18em] text-sky-400">
            Matchup Projection
          </p>

          <h2 className="mt-2 text-2xl font-semibold">
            Model view of the game
            itself.
          </h2>

          {projectionError && (
            <p className="mt-4 text-sm text-amber-400">
              {projectionError}
            </p>
          )}

          {projection && (
            <>
              <div className="mt-5 rounded-3xl border border-white/[0.08] bg-[linear-gradient(135deg,#101722_0%,#0B1017_100%)] p-8">

                <p className="text-[11px] uppercase tracking-[0.18em] text-zinc-700">
                  Projected Score
                </p>

                <div className="mt-7 grid grid-cols-[1fr_auto_1fr] items-center gap-5">

                  <div>
                    <p className="text-sm text-zinc-500">
                      {
                        projection.awayTeam
                      }
                    </p>

                    <p className="mt-2 text-5xl font-semibold">
                      {projection.model.projectedScore.away.toFixed(
                        1
                      )}
                    </p>
                  </div>

                  <div className="text-zinc-700">
                    @
                  </div>

                  <div className="text-right">
                    <p className="text-sm text-zinc-500">
                      {
                        projection.homeTeam
                      }
                    </p>

                    <p className="mt-2 text-5xl font-semibold">
                      {projection.model.projectedScore.home.toFixed(
                        1
                      )}
                    </p>
                  </div>
                </div>

                <div className="mt-8 grid gap-3 border-t border-white/[0.07] pt-6 md:grid-cols-3">

                  <div>
                    <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                      Model Total
                    </p>

                    <p className="mt-2 text-xl font-semibold">
                      {projection.model.total.toFixed(
                        1
                      )}
                    </p>
                  </div>

                  <div>
                    <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                      Market Total
                    </p>

                    <p className="mt-2 text-xl font-semibold">
                      {projection.market.total.toFixed(
                        1
                      )}
                    </p>
                  </div>

                  <div>
                    <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                      Difference
                    </p>

                    <p className="mt-2 text-xl font-semibold">
                      {formatSignedNumber(
                        Number(
                          (
                            projection
                              .model
                              .total -
                            projection
                              .market
                              .total
                          ).toFixed(
                            1
                          )
                        )
                      )}
                    </p>
                  </div>
                </div>
              </div>

              <div className="mt-4 grid gap-4 lg:grid-cols-2">

                <article className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7">

                  <p className="text-xs uppercase tracking-[0.18em] text-zinc-700">
                    Model vs Market
                  </p>

                  <h3 className="mt-3 text-2xl font-semibold">
                    Where the matchup
                    model disagrees.
                  </h3>

                  <div className="mt-6 space-y-5">

                    <div className="flex justify-between border-b border-white/[0.07] pb-4">
                      <span className="text-zinc-500">
                        Model margin —
                        home
                      </span>

                      <span className="font-semibold">
                        {formatSignedNumber(
                          projection
                            .model
                            .marginHome
                        )}
                      </span>
                    </div>

                    <div className="flex justify-between border-b border-white/[0.07] pb-4">
                      <span className="text-zinc-500">
                        Market margin —
                        home
                      </span>

                      <span className="font-semibold">
                        {formatSignedNumber(
                          projection
                            .market
                            .marginHome
                        )}
                      </span>
                    </div>

                    <div className="flex justify-between">
                      <span className="text-zinc-500">
                        Spread edge
                      </span>

                      <span className="font-semibold text-emerald-400">
                        {formatSignedNumber(
                          projection
                            .spreadAnalysis
                            .edgePoints
                        )}{" "}
                        pts
                      </span>
                    </div>
                  </div>
                </article>

                <article className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7">

                  <p className="text-xs uppercase tracking-[0.18em] text-zinc-700">
                    Team Power
                  </p>

                  <h3 className="mt-3 text-2xl font-semibold">
                    Relative
                    team-strength signal.
                  </h3>

                  <div className="mt-6 grid grid-cols-2 gap-3">

                    <div className="rounded-xl border border-white/[0.07] p-5">
                      <p className="text-zinc-500">
                        {
                          projection.awayTeam
                        }
                      </p>

                      <p className="mt-2 text-3xl font-semibold">
                        {projection.teamPower.away.toFixed(
                          2
                        )}
                      </p>
                    </div>

                    <div className="rounded-xl border border-white/[0.07] p-5">
                      <p className="text-zinc-500">
                        {
                          projection.homeTeam
                        }
                      </p>

                      <p className="mt-2 text-3xl font-semibold">
                        {projection.teamPower.home.toFixed(
                          2
                        )}
                      </p>
                    </div>
                  </div>

                  <div className="mt-4 rounded-xl border border-white/[0.07] p-5">

                    <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                      Home Minus Away
                      Power
                    </p>

                    <p className="mt-2 text-2xl font-semibold">
                      {formatSignedNumber(
                        projection
                          .teamPower
                          .differenceHomeMinusAway
                      )}
                    </p>
                  </div>
                </article>
              </div>

              <div className="mt-4 rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7">

                <p className="text-xs uppercase tracking-[0.18em] text-zinc-700">
                  Spread Projection
                </p>

                <div className="mt-5 grid gap-4 md:grid-cols-3">

                  <div className="rounded-xl border border-white/[0.07] p-5">
                    <p className="text-[11px] uppercase tracking-[0.14em] text-zinc-700">
                      Market Home
                      Spread
                    </p>

                    <p className="mt-3 text-2xl font-semibold">
                      {formatSignedNumber(
                        projection
                          .market
                          .homeSpread
                      )}
                    </p>
                  </div>

                  <div className="rounded-xl border border-white/[0.07] p-5">
                    <p className="text-[11px] uppercase tracking-[0.14em] text-zinc-700">
                      Home Cover
                      Probability
                    </p>

                    <p className="mt-3 text-2xl font-semibold">
                      {projection.spreadAnalysis.homeCoverProbability.toFixed(
                        1
                      )}
                      %
                    </p>
                  </div>

                  <div className="rounded-xl border border-white/[0.07] p-5">
                    <p className="text-[11px] uppercase tracking-[0.14em] text-zinc-700">
                      Home Cover Fair
                      Odds
                    </p>

                    <p className="mt-3 text-2xl font-semibold">
                      {formatOdds(
                        projection
                          .spreadAnalysis
                          .homeCoverFairOdds
                      )}
                    </p>
                  </div>
                </div>
              </div>
            </>
          )}
        </section>

        {/* SCHEDULE CONTEXT */}

        <section className="mt-8">

          <p className="text-xs font-medium uppercase tracking-[0.18em] text-violet-400">
            Schedule Context
          </p>

          <h2 className="mt-2 text-2xl font-semibold">
            Rest, travel, and
            scheduling pressure.
          </h2>

          {contextError && (
            <p className="mt-4 text-sm text-amber-400">
              {contextError}
            </p>
          )}

          {context && (
            <>
              <div className="mt-5 grid gap-4 md:grid-cols-2 lg:grid-cols-4">

                <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                    Rest Outlook
                  </p>

                  <p className="mt-3 text-xl font-semibold">
                    {
                      context.rest
                        .label
                    }
                  </p>
                </div>

                <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                    Away Travel
                  </p>

                  <p className="mt-3 text-2xl font-semibold">
                    {context.travel.awayMiles !==
                    null
                      ? `${context.travel.awayMiles.toFixed(
                          0
                        )} mi`
                      : "N/A"}
                  </p>
                </div>

                <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                    Timezone Shift
                  </p>

                  <p className="mt-3 text-2xl font-semibold">
                    {context.travel.awayTimezoneShiftHours !==
                    null
                      ? `${context.travel.awayTimezoneShiftHours.toFixed(
                          1
                        )} hr`
                      : "N/A"}
                  </p>
                </div>

                <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                    Week
                  </p>

                  <p className="mt-3 text-2xl font-semibold">
                    {context.week}
                  </p>
                </div>
              </div>

              <div className="mt-4 grid gap-4 lg:grid-cols-2">

                <article className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7">

                  <p className="text-xs uppercase tracking-[0.18em] text-zinc-700">
                    Rest Profile
                  </p>

                  <div className="mt-6 space-y-4">

                    <div className="flex justify-between">
                      <span className="text-sm text-zinc-500">
                        {
                          context.awayTeam
                        }{" "}
                        rest
                      </span>

                      <span>
                        {context.rest.weekOneNeutralized
                          ? "Offseason"
                          : `${context.rest.awayDays ?? "N/A"} days`}
                      </span>
                    </div>

                    <div className="flex justify-between">
                      <span className="text-sm text-zinc-500">
                        {
                          context.homeTeam
                        }{" "}
                        rest
                      </span>

                      <span>
                        {context.rest.weekOneNeutralized
                          ? "Offseason"
                          : `${context.rest.homeDays ?? "N/A"} days`}
                      </span>
                    </div>

                    <div className="flex justify-between">
                      <span className="text-sm text-zinc-500">
                        Rest advantage
                      </span>

                      <span>
                        {context.rest.weekOneNeutralized
                          ? "Neutral"
                          : `${formatSignedNumber(
                              context
                                .rest
                                .advantageHomeDays ??
                                0
                            )} days`}
                      </span>
                    </div>
                  </div>
                </article>

                <article className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7">

                  <p className="text-xs uppercase tracking-[0.18em] text-zinc-700">
                    Schedule Flags
                  </p>

                  <div className="mt-6 grid grid-cols-2 gap-3">

                    <div className="rounded-xl border border-white/[0.07] p-4">
                      <p className="text-xs text-zinc-600">
                        Away Short Rest
                      </p>

                      <p className="mt-2 font-semibold">
                        {context.rest.shortRestAway
                          ? "Yes"
                          : "No"}
                      </p>
                    </div>

                    <div className="rounded-xl border border-white/[0.07] p-4">
                      <p className="text-xs text-zinc-600">
                        Home Short Rest
                      </p>

                      <p className="mt-2 font-semibold">
                        {context.rest.shortRestHome
                          ? "Yes"
                          : "No"}
                      </p>
                    </div>

                    <div className="rounded-xl border border-white/[0.07] p-4">
                      <p className="text-xs text-zinc-600">
                        Away Long Rest
                      </p>

                      <p className="mt-2 font-semibold">
                        {context.rest.longRestAway
                          ? "Yes"
                          : "No"}
                      </p>
                    </div>

                    <div className="rounded-xl border border-white/[0.07] p-4">
                      <p className="text-xs text-zinc-600">
                        Home Long Rest
                      </p>

                      <p className="mt-2 font-semibold">
                        {context.rest.longRestHome
                          ? "Yes"
                          : "No"}
                      </p>
                    </div>
                  </div>
                </article>
              </div>
            </>
          )}
        </section>

        {/* MARKET INTELLIGENCE */}

        <section className="mt-10">

          <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-400">
            Market Intelligence
          </p>

          <h2 className="mt-2 text-2xl font-semibold">
            How sportsbook behavior
            supports or resists the
            model.
          </h2>

          <div
            className={`mt-5 rounded-3xl border p-7 ${marketStyle.border}`}
          >

            <div className="flex flex-wrap items-center justify-between gap-5">

              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-zinc-700">
                  Market Signal
                </p>

                <p
                  className={`mt-2 text-2xl font-semibold ${marketStyle.text}`}
                >
                  {market.signal}
                </p>
              </div>

              <div className="text-right">
                <p className="text-xs uppercase tracking-[0.18em] text-zinc-700">
                  Market Score
                </p>

                <p
                  className={`mt-2 text-4xl font-semibold ${marketStyle.text}`}
                >
                  {market.score.toFixed(
                    1
                  )}
                  <span className="text-sm text-zinc-600">
                    /10
                  </span>
                </p>
              </div>
            </div>

            <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">

              <div className="rounded-xl border border-white/[0.06] bg-black/10 p-4">
                <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                  Books Moving
                </p>

                <p className="mt-2 text-xl font-semibold">
                  {
                    market.booksMoving
                  }{" "}
                  /{" "}
                  {
                    market.booksTracked
                  }
                </p>
              </div>

              <div className="rounded-xl border border-white/[0.06] bg-black/10 p-4">
                <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                  Steam Books
                </p>

                <p className="mt-2 text-xl font-semibold">
                  {
                    market.steamBooks
                  }
                </p>
              </div>

              <div className="rounded-xl border border-white/[0.06] bg-black/10 p-4">
                <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                  Directional
                  Consensus
                </p>

                <p className="mt-2 text-xl font-semibold">
                  {market.consensus.toFixed(
                    0
                  )}
                  %
                </p>
              </div>

              <div className="rounded-xl border border-white/[0.06] bg-black/10 p-4">
                <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                  Snapshots
                </p>

                <p className="mt-2 text-xl font-semibold">
                  {
                    market.snapshots
                  }
                </p>
              </div>
            </div>
          </div>

          {/* SPORTSBOOK TABLE */}

          <div className="mt-4 overflow-hidden rounded-3xl border border-white/[0.08] bg-[#0D131C]">

            <div className="grid grid-cols-[1.4fr_0.8fr_0.8fr_0.8fr] gap-3 border-b border-white/[0.07] px-6 py-4 text-[11px] uppercase tracking-[0.14em] text-zinc-700">

              <span>
                Sportsbook
              </span>

              <span>
                Line
              </span>

              <span>
                Price
              </span>

              <span>
                EV / $1
              </span>
            </div>

            <div className="grid grid-cols-[1.4fr_0.8fr_0.8fr_0.8fr] gap-3 bg-emerald-400/[0.035] px-6 py-5">

              <div className="flex items-center gap-2">

                <span className="font-semibold">
                  {
                    opportunity.book
                  }
                </span>

                <Badge className="bg-emerald-400 text-black hover:bg-emerald-400">
                  Best
                </Badge>
              </div>

              <span>
                {formatPoint(
                  opportunity.market,
                  opportunity.side,
                  opportunity.point
                )}
              </span>

              <span>
                {formatOdds(
                  opportunity.price
                )}
              </span>

              <span className="text-emerald-400">
                +$
                {opportunity.evPerDollar.toFixed(
                  3
                )}
              </span>
            </div>

            {alternateBooks.map(
              (book) => (
                <div
                  key={`${book.book}-${book.point}-${book.price}`}
                  className="grid grid-cols-[1.4fr_0.8fr_0.8fr_0.8fr] gap-3 border-t border-white/[0.06] px-6 py-5 text-sm"
                >
                  <span>
                    {book.book}
                  </span>

                  <span>
                    {formatPoint(
                      opportunity.market,
                      opportunity.side,
                      book.point
                    )}
                  </span>

                  <span>
                    {formatOdds(
                      book.price
                    )}
                  </span>

                  <span>
                    +$
                    {book.evPerDollar.toFixed(
                      3
                    )}
                  </span>
                </div>
              )
            )}

            {alternateBooks.length ===
              0 && (
              <div className="border-t border-white/[0.06] px-6 py-6">
                <p className="text-sm text-zinc-600">
                  No alternate
                  sportsbook prices are
                  currently available.
                </p>
              </div>
            )}
          </div>
        </section>

        {/* MODEL METRICS */}

        <section className="mt-8 grid gap-4 md:grid-cols-2 lg:grid-cols-4">

          <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">

            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Model Probability
            </p>

            <p className="mt-3 text-2xl font-semibold">
              {opportunity.modelProbability.toFixed(
                1
              )}
              %
            </p>
          </div>

          <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">

            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Market Implied
            </p>

            <p className="mt-3 text-2xl font-semibold">
              {opportunity.impliedProbability.toFixed(
                1
              )}
              %
            </p>
          </div>

          <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">

            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              20% Kelly
            </p>

            <p className="mt-3 text-2xl font-semibold">
              {(
                opportunity.kelly20 *
                100
              ).toFixed(
                1
              )}
              %
            </p>
          </div>

          <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">

            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Fair Odds
            </p>

            <p className="mt-3 text-2xl font-semibold">
              {formatOdds(
                opportunity.fairOdds
              )}
            </p>
          </div>
        </section>

        {/* SIGNAL QUALITY */}

        <section className="mt-8 grid gap-4 lg:grid-cols-2">

          <article className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7">

            <p className="text-xs uppercase tracking-[0.18em] text-zinc-700">
              Signal Quality
            </p>

            <h3 className="mt-3 text-2xl font-semibold">
              Confidence behind the
              recommendation.
            </h3>

            <div className="mt-6 space-y-5">
              {[
                {
                  label:
                    "Data completeness",
                  value:
                    opportunity.dataCompleteness,
                },
                {
                  label:
                    "Market confidence",
                  value:
                    opportunity.marketConfidence,
                },
                {
                  label:
                    "Model confidence",
                  value:
                    opportunity.modelConfidence,
                },
              ].map(
                (metric) => (
                  <div
                    key={
                      metric.label
                    }
                  >
                    <div className="flex justify-between text-sm">

                      <span className="text-zinc-500">
                        {
                          metric.label
                        }
                      </span>

                      <span>
                        {metric.value.toFixed(
                          0
                        )}
                        %
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
                )
              )}
            </div>
          </article>

          <article className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7">

            <p className="text-xs uppercase tracking-[0.18em] text-zinc-700">
              Position Sizing
            </p>

            <h3 className="mt-3 text-2xl font-semibold">
              Model-derived
              allocation guidance.
            </h3>

            <div className="mt-6 space-y-5">

              <div className="flex justify-between border-b border-white/[0.07] pb-4">

                <span className="text-zinc-500">
                  Full Kelly
                </span>

                <span className="font-semibold">
                  {(
                    opportunity.kellyFull *
                    100
                  ).toFixed(
                    1
                  )}
                  %
                </span>
              </div>

              <div className="flex justify-between border-b border-white/[0.07] pb-4">

                <span className="text-zinc-500">
                  20% Kelly
                </span>

                <span className="font-semibold">
                  {(
                    opportunity.kelly20 *
                    100
                  ).toFixed(
                    1
                  )}
                  %
                </span>
              </div>

              <div className="flex justify-between">

                <span className="text-zinc-500">
                  Expected Value /
                  $1
                </span>

                <span className="font-semibold text-emerald-400">
                  +$
                  {opportunity.evPerDollar.toFixed(
                    3
                  )}
                </span>
              </div>
            </div>
          </article>
        </section>

        {/* BOTTOM LINE */}

        <section className="mt-8 rounded-3xl border border-emerald-400/15 bg-emerald-400/[0.035] p-8">

          <p className="text-xs uppercase tracking-[0.18em] text-emerald-400">
            Bottom Line
          </p>

          <h2 className="mt-3 text-3xl font-semibold">
            {opportunity.pick}:{" "}
            {sportsScore.recommendation}.
          </h2>

          <p className="mt-4 max-w-3xl text-sm leading-7 text-zinc-400">
            The Sports Intelligence
            Score is currently{" "}
            {sportsScore.score.toFixed(
              1
            )}
            /100 with a{" "}
            {sportsScore.grade} grade.
            The model sees strong
            expected value, while
            observed market behavior is
            currently graded{" "}
            {market.grade}. Continue
            monitoring price, injuries,
            market movement, and other
            contextual changes before
            kickoff.
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
                className="border-white/10 bg-transparent text-white"
              >
                Back to
                Opportunities
              </Button>
            </Link>
          </div>
          {snapshotError && (
            <p className="mt-2 text-xs text-amber-400">{snapshotError}</p>
          )}
        </section>
      </div>
    </main>
  );
}