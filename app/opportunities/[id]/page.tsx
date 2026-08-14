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
import FreshnessBadge from "@/components/ui/freshness-badge";
import Tooltip from "@/components/ui/tooltip";

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
    injuryContext?: number;
  };

  weights: {
    modelEdge: number;
    expectedValue: number;
    confidence: number;
    marketIntelligence: number;
    dataCompleteness: number;
    injuryContext?: number;
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

  injuryContext?: {
    awayInjuryScore?: number;
    homeInjuryScore?: number;
    severity?: string;
    summary?: string;
    keyInjuries?: string[];
    providerMetadata?: { dataStatus?: string; isLive?: boolean; lastUpdated?: string | null };
  } | null;
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

// ── Deterministic explanation helpers ───────────────────────────────────────

function buildWhySIALikes(opp: Opportunity, weatherStatus: { dataStatus?: string } | null): string {
  const { pick, modelProbability, impliedProbability, edge, evPerDollar, sportsIntelligenceScore: si, marketIntelligence: mi } = opp;
  const prob = `SIA gives ${pick} a ${modelProbability.toFixed(1)}% win probability compared with the market's ${impliedProbability.toFixed(1)}% implied probability, creating a ${edge.toFixed(1)}-point model edge.`;
  const ev = evPerDollar >= 0.08 ? ` The current price generates ${evPerDollar >= 0.20 ? "strong" : "positive"} expected value (+$${evPerDollar.toFixed(3)} per dollar wagered).` : "";
  let mkt = "";
  if (mi.score >= 7) mkt = " Market movement has confirmed the model's direction.";
  else if (mi.score >= 5) mkt = " Market confirmation is mixed, which tempers overall conviction.";
  else mkt = " The market has not yet confirmed the model's direction.";
  const rec = si.recommendation;
  const tier = rec === "Elite Bet" || rec === "Strong Bet" ? ` This keeps the recommendation at ${rec}.` : ` The overall setup is graded as a ${rec}.`;
  return `${prob}${ev}${mkt}${tier}`;
}

function buildSupportingSignals(opp: Opportunity): string[] {
  const signals: string[] = [];
  if (opp.edge >= 20) signals.push("Exceptional model edge over the current market");
  else if (opp.edge >= 12) signals.push("Strong model edge over the current market");
  else if (opp.edge >= 5) signals.push("Positive model edge is present");
  if (opp.evPerDollar >= 0.20) signals.push("Strong expected value at the current price");
  else if (opp.evPerDollar >= 0.08) signals.push("Positive expected value at the current price");
  if (opp.confidence >= 80) signals.push("High model confidence");
  else if (opp.confidence >= 65) signals.push("Solid model confidence");
  const mi = opp.marketIntelligence;
  if (mi.score >= 7) signals.push("Sportsbook movement confirms the model");
  else if (mi.score >= 5 && mi.consensus >= 60) signals.push("Directional market agreement present");
  if (opp.dataCompleteness >= 85) signals.push("Strong underlying data coverage");
  const injSev = opp.injuryContext?.severity?.toLowerCase() ?? "neutral";
  if (injSev === "neutral" || injSev === "small") signals.push("No material injury concern");
  return signals.slice(0, 4);
}

function buildCautionSignals(opp: Opportunity, weatherStatus: { dataStatus?: string } | null): string[] {
  const cautions: string[] = [];
  const mi = opp.marketIntelligence;
  if (mi.score < 5) cautions.push("The market has not confirmed the model's direction");
  else if (mi.score < 7) cautions.push("Market confirmation is mixed");
  if (weatherStatus?.dataStatus === "UNAVAILABLE") cautions.push("Game-time weather forecast not yet available");
  if (opp.dataCompleteness < 70) cautions.push("Incomplete underlying data reduces conviction");
  const injSev = opp.injuryContext?.severity?.toLowerCase() ?? "neutral";
  if (injSev === "moderate") cautions.push("Injury context is a moderate concern");
  else if (injSev === "significant" || injSev === "major") cautions.push("Injury context is a material headwind");
  if (opp.edge < 5) cautions.push("Model edge is modest");
  return cautions.slice(0, 4);
}

function buildMarketScoreExplanation(market: MarketIntelligence): string {
  const { score, booksMoving, booksTracked, steamBooks, consensus, snapshots } = market;
  const level = score >= 7 ? "strong" : score >= 5 ? "moderate" : "limited";
  const movePart = booksTracked > 0
    ? `${booksMoving} of ${booksTracked} tracked sportsbooks have moved on this market`
    : "no sportsbook movement data available";
  const steamPart = steamBooks >= 2
    ? `${steamBooks} sharp steam signals detected`
    : steamBooks === 1
    ? "one sharp steam signal has appeared"
    : "no sharp steam signals detected";
  const consensusPart = consensus >= 75
    ? `directional agreement is strong at ${consensus.toFixed(0)}%`
    : consensus >= 55
    ? `directional agreement is moderate at ${consensus.toFixed(0)}%`
    : `directional agreement is mixed at ${consensus.toFixed(0)}%`;
  const snapshotPart = snapshots >= 5
    ? `${snapshots} market updates recorded`
    : `limited market history (${snapshots} updates)`;
  return `Market confirmation is ${level}: ${movePart}; ${steamPart}; ${consensusPart}; ${snapshotPart}.`;
}

function componentExplanation(name: string, score: number): string {
  if (name === "modelEdge") {
    if (score >= 80) return "SIA's estimated probability materially exceeds the market-implied probability.";
    if (score >= 40) return "The model sees a moderate edge over the current market price.";
    return "The model edge over the current market price is limited.";
  }
  if (name === "expectedValue") {
    if (score >= 80) return "The current price generates strong positive expected value per dollar.";
    if (score >= 30) return "The price produces positive but moderate expected value.";
    return "Expected value at current odds is limited.";
  }
  if (name === "confidence") {
    if (score >= 80) return "The model's win probability estimate has high internal consistency.";
    if (score >= 60) return "Model confidence is solid.";
    return "Model confidence is moderate — additional signals would improve conviction.";
  }
  if (name === "marketIntelligence") {
    if (score >= 70) return "Sportsbook movement has confirmed the model's direction.";
    if (score >= 40) return "Sportsbook movement has not strongly confirmed the model.";
    return "The market has not yet confirmed the model signal.";
  }
  if (name === "dataCompleteness") {
    if (score >= 80) return "Underlying data coverage is strong.";
    if (score >= 60) return "Data coverage is adequate but not complete.";
    return "Data coverage is incomplete, which reduces conviction.";
  }
  if (name === "injuryContext") {
    if (score >= 90) return "No material injury factor is affecting this position.";
    if (score >= 60) return "Injury context is a moderate consideration for this game.";
    return "Injury context is a meaningful headwind for this position.";
  }
  return "";
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
  const [weatherStatus, setWeatherStatus] = useState<{ dataStatus?: string; lastUpdated?: string | null } | null>(null);
  const [showFullExplainability, setShowFullExplainability] = useState(false);
  const [showMarketDetails, setShowMarketDetails] = useState(false);

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

        // Fetch weather status alongside projection/context
        const [
          projectionResult,
          contextResult,
          weatherResult,
        ] =
          await Promise.allSettled([
            fetchJson<GameProjection>(`/api/games/${opportunityData.eventId}`),
            fetchJson<ScheduleContext>(`/api/games/${opportunityData.eventId}/context`),
            fetchJson<{ dataStatus?: string; lastUpdated?: string | null }>(`/api/games/${opportunityData.eventId}/weather`),
          ]);

        if (weatherResult.status === "fulfilled") {
          setWeatherStatus({ dataStatus: weatherResult.value.dataStatus, lastUpdated: weatherResult.value.lastUpdated });
        }

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
        const msg = err instanceof Error ? err.message : "";
        setError(
          msg.includes("404")
            ? "Opportunity not found."
            : "Unable to load this opportunity."
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
              className={`${marketStyle.border} ${marketStyle.text} inline-flex items-center gap-0.5`}
            >
              Market {market.grade}
              <Tooltip term="Market Grade" />
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
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700 inline-flex items-center">
                  Confidence
                  <Tooltip term="Confidence" />
                </p>

                <p className="mt-1 text-3xl font-semibold">
                  {
                    opportunity.confidence
                  }<span className="text-xl text-zinc-500">/100</span>
                </p>
              </div>

              <div>
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700 inline-flex items-center">
                  Model Edge
                  <Tooltip term="Model Edge" />
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
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700 inline-flex items-center">
                  EV / $1
                  <Tooltip term="EV" />
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

        {/* WHY SIA LIKES THIS BET */}

        <section className="mt-10 rounded-3xl border border-white/[0.08] bg-[#0B1119] p-7 lg:p-8">
          <p className="text-[11px] uppercase tracking-[0.22em] text-emerald-400">Why SIA Likes This Bet</p>
          <p className="mt-4 text-base leading-8 text-zinc-300">
            {buildWhySIALikes(opportunity, weatherStatus)}
          </p>

          <div className="mt-6 grid gap-4 sm:grid-cols-2">
            {/* Supporting signals */}
            {buildSupportingSignals(opportunity).length > 0 && (
              <div className="rounded-2xl border border-emerald-400/15 bg-emerald-400/[0.04] p-5">
                <p className="text-[10px] uppercase tracking-[0.2em] text-emerald-400">Supporting This Bet</p>
                <ul className="mt-3 space-y-2">
                  {buildSupportingSignals(opportunity).map((s) => (
                    <li key={s} className="flex items-start gap-2 text-sm text-zinc-300">
                      <span className="mt-0.5 text-emerald-400">✓</span>
                      {s}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Caution signals */}
            {buildCautionSignals(opportunity, weatherStatus).length > 0 && (
              <div className="rounded-2xl border border-amber-400/15 bg-amber-400/[0.04] p-5">
                <p className="text-[10px] uppercase tracking-[0.2em] text-amber-400">What Holds It Back</p>
                <ul className="mt-3 space-y-2">
                  {buildCautionSignals(opportunity, weatherStatus).map((s) => (
                    <li key={s} className="flex items-start gap-2 text-sm text-zinc-300">
                      <span className="mt-0.5 text-amber-400">–</span>
                      {s}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <div className="mt-6 flex flex-wrap gap-3">
            <button
              onClick={addToCard}
              disabled={added}
              className={`rounded-xl border px-5 py-2.5 text-sm font-medium transition ${added ? "border-emerald-400/30 bg-emerald-400/10 text-emerald-300" : "border-white/10 bg-white text-black hover:bg-zinc-200"}`}
            >
              {added ? "Added to My Card ✓" : "Add to My Card"}
            </button>
            <Link href="/my-card">
              <button className="rounded-xl border border-white/10 bg-transparent px-5 py-2.5 text-sm text-white transition hover:bg-white/[0.05]">
                Review My Card →
              </button>
            </Link>
          </div>
          {snapshotError && <p className="mt-2 text-xs text-amber-400">{snapshotError}</p>}
        </section>

        {/* SPORTS INTELLIGENCE SCORE */}

        <section className="mt-8">

          <SportsIntelligenceScoreCard
            score={sportsScore}
          />

          {/* COMPACT SCORE BREAKDOWN */}

          <div className="mt-6 rounded-3xl border border-white/[0.08] bg-[#0B1119] p-6 lg:p-8">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600">Score Breakdown</p>
                <h3 className="mt-1 text-xl font-semibold tracking-tight">
                  Why this scored {sportsScore.score.toFixed(1)}
                </h3>
              </div>
              <div className="rounded-full border border-white/[0.08] bg-white/[0.04] px-3 py-1 text-xs text-zinc-500">
                Deterministic rules-based
              </div>
            </div>

            <div className="mt-5 divide-y divide-white/[0.05]">
              {([
                ["modelEdge",         "Model Edge",      sportsScore.components.modelEdge,         sportsScore.weights.modelEdge],
                ["expectedValue",     "Expected Value",  sportsScore.components.expectedValue,     sportsScore.weights.expectedValue],
                ["confidence",        "Confidence",      sportsScore.components.confidence,        sportsScore.weights.confidence],
                ["marketIntelligence","Market",          sportsScore.components.marketIntelligence,sportsScore.weights.marketIntelligence],
                ["dataCompleteness",  "Data Quality",    sportsScore.components.dataCompleteness,  sportsScore.weights.dataCompleteness],
                ...(sportsScore.components.injuryContext != null
                  ? [["injuryContext", "Injury Context",  sportsScore.components.injuryContext,    sportsScore.weights.injuryContext] as const]
                  : []),
              ] as [string, string, number, number][]).map(([key, label, score, weight]) => (
                <div key={key} className="grid grid-cols-[1fr_auto_auto] items-center gap-4 py-3 sm:grid-cols-[2fr_1fr_1fr_3fr]">
                  <span className="text-sm text-zinc-300">{label}</span>
                  <span className={`text-sm font-semibold ${score >= 75 ? "text-emerald-400" : score >= 50 ? "text-sky-400" : "text-amber-400"}`}>
                    {score.toFixed(0)}<span className="text-xs text-zinc-600">/100</span>
                  </span>
                  <span className="text-xs text-zinc-600">{weight}%</span>
                  <span className="hidden text-xs leading-5 text-zinc-500 sm:block">{componentExplanation(key, score)}</span>
                </div>
              ))}
            </div>

            {/* FULL EXPLANATION COLLAPSIBLE */}
            <button
              onClick={() => setShowFullExplainability((v) => !v)}
              className="mt-5 flex items-center gap-2 text-xs text-zinc-500 transition hover:text-zinc-300"
            >
              <span>{showFullExplainability ? "▲ Hide Full Explanation" : "▼ See Full Score Explanation"}</span>
            </button>

            {showFullExplainability && explainability && (
              <div className="mt-6 space-y-6">
                <p className="max-w-3xl text-sm leading-7 text-zinc-400">{explainability.overallSummary}</p>

                <div className="grid gap-6 lg:grid-cols-2">
                  <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                    <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">Strengths</p>
                    <ul className="mt-4 space-y-2 text-sm text-zinc-400">
                      {explainability.strengths.map((item) => <li key={item}>• {item}</li>)}
                    </ul>
                  </div>
                  <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                    <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">Weaknesses</p>
                    <ul className="mt-4 space-y-2 text-sm text-zinc-400">
                      {explainability.weaknesses.map((item) => <li key={item}>• {item}</li>)}
                    </ul>
                  </div>
                </div>

                <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                  <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                    <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">Confidence</p>
                    <p className="mt-3 text-sm leading-7 text-zinc-400">{explainability.confidenceExplanation}</p>
                  </div>
                  <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                    <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">Market</p>
                    <p className="mt-3 text-sm leading-7 text-zinc-400">{explainability.marketExplanation}</p>
                  </div>
                  <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">Injury</p>
                      {opportunity.injuryContext?.providerMetadata?.dataStatus && (
                        <FreshnessBadge status={opportunity.injuryContext.providerMetadata.dataStatus} lastUpdated={opportunity.injuryContext.providerMetadata.lastUpdated} />
                      )}
                    </div>
                    <p className="mt-3 text-sm leading-7 text-zinc-400">{explainability.injuryExplanation}</p>
                  </div>
                  <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">Weather</p>
                      {weatherStatus?.dataStatus ? (
                        <FreshnessBadge status={weatherStatus.dataStatus} lastUpdated={weatherStatus.lastUpdated} />
                      ) : (
                        <span className="text-[10px] text-zinc-600">Forecast not yet available</span>
                      )}
                    </div>
                    <p className="mt-3 text-sm leading-7 text-zinc-400">{explainability.weatherExplanation}</p>
                    {weatherStatus?.dataStatus === "UNAVAILABLE" && (
                      <p className="mt-2 text-[11px] text-zinc-600">Game-time forecast not available yet — game may be outside the 16-day forecast window.</p>
                    )}
                  </div>
                </div>

                <div className="grid gap-4 lg:grid-cols-3">
                  <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                    <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">Key reasons</p>
                    <ul className="mt-4 space-y-2 text-sm text-zinc-400">
                      {explainability.keyReasons.map((item) => <li key={item}>• {item}</li>)}
                    </ul>
                  </div>
                  <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                    <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">What could improve</p>
                    <ul className="mt-4 space-y-2 text-sm text-zinc-400">
                      {explainability.whatCouldImprove.map((item) => <li key={item}>• {item}</li>)}
                    </ul>
                  </div>
                  <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-5">
                    <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">Risk factors</p>
                    <ul className="mt-4 space-y-2 text-sm text-zinc-400">
                      {explainability.riskFactors.map((item) => <li key={item}>• {item}</li>)}
                    </ul>
                  </div>
                </div>
              </div>
            )}
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

        {/* DECISION TIMELINE — only shown when there is at least one meaningful event */}

        {decisionTimeline && decisionTimeline.timeline.length > 0 && (
        <section className="mt-8 rounded-3xl border border-white/[0.08] bg-[#0B1119] p-8 lg:p-10">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.18em] text-sky-400">Decision Timeline</p>
              <h2 className="mt-2 text-3xl font-semibold tracking-tight">Every meaningful change that shaped this recommendation</h2>
            </div>
            <div className="rounded-full border border-white/[0.08] bg-white/[0.04] px-3 py-1 text-sm text-zinc-400">
              {decisionTimeline.changeCount} updates
            </div>
          </div>

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
        </section>
        )}

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

            {/* Simplified 3-signal view */}
            <div className="mt-6 grid gap-3 sm:grid-cols-3">

              <div className="rounded-xl border border-white/[0.06] bg-black/10 p-4">
                <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                  Sportsbooks Moving
                </p>
                <p className="mt-2 text-xl font-semibold">
                  {market.booksMoving} of {market.booksTracked}
                </p>
              </div>

              <div className="rounded-xl border border-white/[0.06] bg-black/10 p-4">
                <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                  Market Agreement
                </p>
                <p className="mt-2 text-xl font-semibold">
                  {market.consensus >= 70 ? "Strong" : market.consensus >= 55 ? "Moderate" : "Mixed"}
                </p>
              </div>

              <div className="rounded-xl border border-white/[0.06] bg-black/10 p-4">
                <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                  Sharp Movement
                </p>
                <p className="mt-2 text-xl font-semibold">
                  {market.steamBooks >= 2 ? "Confirmed" : market.steamBooks === 1 ? "Limited" : "None detected"}
                </p>
              </div>
            </div>

            {/* Plain-English market score explanation */}
            <p className="mt-4 text-sm leading-7 text-zinc-400">
              {buildMarketScoreExplanation(market)}
            </p>

            {/* Toggle for full technical detail */}
            <button
              onClick={() => setShowMarketDetails((v) => !v)}
              className="mt-4 flex items-center gap-2 text-xs text-zinc-500 transition hover:text-zinc-300"
            >
              {showMarketDetails ? "▲ Hide Market Details" : "▼ View Market Details"}
            </button>

            {showMarketDetails && (
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-xl border border-white/[0.06] bg-black/10 p-4">
                  <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                    Books Moving
                    <Tooltip term="Books Moving" />
                  </p>
                  <p className="mt-2 text-xl font-semibold">
                    {market.booksMoving} / {market.booksTracked}
                  </p>
                </div>
                <div className="rounded-xl border border-white/[0.06] bg-black/10 p-4">
                  <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                    Sharp Steam Signals
                    <Tooltip term="Steam Books" />
                  </p>
                  <p className="mt-2 text-xl font-semibold">{market.steamBooks}</p>
                </div>
                <div className="rounded-xl border border-white/[0.06] bg-black/10 p-4">
                  <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                    Directional Consensus
                    <Tooltip term="Directional Consensus" />
                  </p>
                  <p className="mt-2 text-xl font-semibold">{market.consensus.toFixed(0)}%</p>
                </div>
                <div className="rounded-xl border border-white/[0.06] bg-black/10 p-4">
                  <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                    Market Updates
                    <Tooltip term="Snapshots" />
                  </p>
                  <p className="mt-2 text-xl font-semibold">{market.snapshots}</p>
                </div>
                {market.supportingBooks > 0 || market.opposingBooks > 0 ? (
                  <>
                    <div className="rounded-xl border border-white/[0.06] bg-black/10 p-4">
                      <p className="text-[10px] uppercase tracking-wider text-zinc-700">Supporting Books</p>
                      <p className="mt-2 text-xl font-semibold">{market.supportingBooks}</p>
                    </div>
                    <div className="rounded-xl border border-white/[0.06] bg-black/10 p-4">
                      <p className="text-[10px] uppercase tracking-wider text-zinc-700">Opposing Books</p>
                      <p className="mt-2 text-xl font-semibold">{market.opposingBooks}</p>
                    </div>
                  </>
                ) : null}
                {market.largestPointMove > 0 && (
                  <div className="rounded-xl border border-white/[0.06] bg-black/10 p-4">
                    <p className="text-[10px] uppercase tracking-wider text-zinc-700">Largest Point Move</p>
                    <p className="mt-2 text-xl font-semibold">{market.largestPointMove.toFixed(1)}</p>
                  </div>
                )}
                {market.largestPriceMove > 0 && (
                  <div className="rounded-xl border border-white/[0.06] bg-black/10 p-4">
                    <p className="text-[10px] uppercase tracking-wider text-zinc-700">Largest Price Move</p>
                    <p className="mt-2 text-xl font-semibold">{market.largestPriceMove.toFixed(0)}</p>
                  </div>
                )}
              </div>
            )}
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

            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700 inline-flex items-center">
              Model Probability
              <Tooltip term="Model Probability" />
            </p>

            <p className="mt-3 text-2xl font-semibold">
              {opportunity.modelProbability.toFixed(
                1
              )}
              %
            </p>
          </div>

          <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">

            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700 inline-flex items-center">
              Market Implied
              <Tooltip term="Market Implied" />
            </p>

            <p className="mt-3 text-2xl font-semibold">
              {opportunity.impliedProbability.toFixed(
                1
              )}
              %
            </p>
          </div>

          <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">

            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700 inline-flex items-center">
              20% Kelly
              <Tooltip term="Kelly 20%" />
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

            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700 inline-flex items-center">
              Fair Odds
              <Tooltip term="Fair Odds" />
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