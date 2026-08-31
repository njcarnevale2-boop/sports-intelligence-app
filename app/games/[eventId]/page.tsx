"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fetchJson } from "../../lib/api";
import { addToCard as addToCardHelper } from "@/lib/add-to-card";
import { formatKickoffDateEt, formatKickoffTimeEt } from "@/app/lib/time-format";
import {
  formatTravelMiles,
  formatTravelShift,
  getRestLabel,
  hasScheduleContext,
  type InjuryContext,
  type ScheduleContext,
} from "@/app/lib/page-context";

type GameProjection = {
  eventId: string;
  commenceTime: string;
  awayTeam: string;
  homeTeam: string;
  model: { projectedScore: { away: number; home: number } };
  market: { homeSpread: number; total: number };
  spreadAnalysis: { edgePoints: number };
};

type MarketIntelligence = {
  score: number;
  signal: string;
  steamBooks: number;
  booksMoving: number;
  booksTracked: number;
};

type SportsIntelligenceScore = {
  score: number;
  recommendation: string;
  components: {
    modelEdge: number;
    expectedValue: number;
    confidence: number;
    marketIntelligence: number;
    dataCompleteness: number;
  };
};

type Opportunity = {
  id: string;
  market: string;
  pick: string;
  book: string;
  point: number | null;
  price: number;
  modelProbability: number;
  impliedProbability: number;
  edge: number;
  evPerDollar: number;
  currentWinProbability?: number | null;
  currentPushProbability?: number | null;
  currentLossProbability?: number | null;
  currentEV?: number | null;
  fairLine?: number | null;
  truePlayableTo?: number | null;
  truePlayableToStatus?: "AVAILABLE" | "UNAVAILABLE";
  truePlayableToReason?: string | null;
  worstObservedPlayablePrice?: number | null;
  worstObservedPlayablePriceStatus?: "AVAILABLE" | "UNAVAILABLE";
  minimumPlayableEV?: number | null;
  confidence: number;
  kelly20: number;
  marketIntelligence: MarketIntelligence;
  sportsIntelligenceScore: SportsIntelligenceScore;
  productionEligible?: boolean;
  marketValidationStatus?: string;
  qualificationStatus?: string;
};

type GameOpportunityResponse = {
  opportunity: Opportunity | null;
  bestByMarket?: Record<string, Opportunity>;
  intelligenceReport?: IntelligenceReport;
};

type IntelligenceReport = {
  betStatus: string;
  qualificationReasons: string[];
  currentLean: string;
  whySummary: string;
  betTrigger: {
    available: boolean;
    message: string;
  };
};

type WeatherStatus = { dataStatus?: string; lastUpdated?: string | null };

type SocialSignal = {
  signalId: string;
  team: string;
  category: string;
  confidence: number;
  textSummary: string;
  sourceName: string;
};

type SocialGameContext = {
  summary?: string;
  provider: string;
  dataStatus: string;
  keySignals: SocialSignal[];
  reason?: string;
};

type CurrentUser = {
  bankroll?: number;
};

type AskSiaResponse = {
  answer: string;
  why: string[];
  whatChangesDecision: string;
  snapshotNote?: string | null;
  missingData?: string[];
};

type MoveTheLineResult = {
  sourceSnapshotId?: string | null;
  contextMode: "LIVE" | "SNAPSHOT";
  current: {
    selection: string;
    spread: number;
    recommendation: string;
    winProbability?: number | null;
    pushProbability?: number | null;
    pushAwareEV?: number | null;
    edge?: number | null;
    truePlayableTo?: number | null;
  };
  hypothetical: {
    selection: string;
    hypotheticalSpread: number;
    assumedOdds: number;
    winProbability: number;
    pushProbability: number;
    lossProbability: number;
    pushAwareEV: number;
    marketImpliedProbability: number;
    edge: number;
    fairLine?: number | null;
    truePlayableTo?: number | null;
    insidePlayableRange?: boolean | null;
    atPlayableBoundary?: boolean;
    qualificationStatus: string;
    recommendation: string;
    decisionStatus: "PLAYABLE" | "PASS" | "UNKNOWN";
    boundaryStatus: "AT_BOUNDARY" | "INSIDE" | "OUTSIDE" | "UNKNOWN";
    status: "PLAYABLE" | "PASS" | "UNKNOWN";
    statusReason: string;
    decisionSummary: string;
    priceDisclosure: string;
  };
  valueChange: {
    probabilityChange?: number | null;
    evChange?: number | null;
    edgeChange?: number | null;
  };
};

type AskSiaMessage = {
  question: string;
  response: AskSiaResponse;
};

function formatKickoff(iso: string) {
  const date = formatKickoffDateEt(iso);
  const time = formatKickoffTimeEt(iso);
  if (date === "TBD" || time === "TBD") return "TBD";
  return `${date} ${time}`;
}

function signed(value: number) {
  return value > 0 ? `+${value}` : `${value}`;
}

function normalizeSpread(value: number) {
  return Math.abs(value) < 0.0001 ? 0 : value;
}

function formatSpread(value: number) {
  const n = normalizeSpread(value);
  if (n === 0) return "PK";
  return n > 0 ? `+${n}` : `${n}`;
}

function stepHalf(value: number, delta: number) {
  const next = Math.round((value + delta) * 2) / 2;
  return normalizeSpread(next);
}

function formatProbabilityUnit(probability: number | null | undefined) {
  if (probability == null) return "Unavailable";
  return `${(probability * 100).toFixed(1)}%`;
}

function formatEv(value: number | null | undefined) {
  if (value == null) return "Unavailable";
  const sign = value >= 0 ? "+" : "";
  return `${sign}$${value.toFixed(3)} per $1`;
}

function formatBestPrice(opp: Opportunity | null) {
  if (!opp) return "Actionable price not currently available";
  if (opp.market === "spread" || opp.market === "total") {
    return `${opp.pick} (${signed(opp.price)}) · ${opp.book}`;
  }
  return `${opp.pick} ${signed(opp.price)} · ${opp.book}`;
}

function formatTruePlayableTo(opp: Opportunity | null) {
  if (!opp) return "Not available yet";
  if (opp.truePlayableToStatus !== "AVAILABLE" || opp.truePlayableTo == null) {
    return "Not available yet";
  }
  if (opp.market === "spread" || opp.market === "total") {
    return `${opp.truePlayableTo > 0 ? "+" : ""}${opp.truePlayableTo}`;
  }
  return signed(opp.truePlayableTo);
}

function marketLabel(opp: Opportunity | null) {
  if (!opp) return "Unavailable";
  if (opp.market === "moneyline") return `${opp.pick} ${signed(opp.price)}`;
  if (opp.market === "total" && opp.point != null) return `${opp.pick} (${signed(opp.price)})`;
  if (opp.market === "spread" && opp.point != null) return `${opp.pick} (${signed(opp.price)})`;
  return `${opp.pick} (${signed(opp.price)})`;
}

function displayWinProbability(opp: Opportunity | null) {
  if (!opp) return null;
  if (opp.currentWinProbability == null) return opp.modelProbability;
  return opp.currentWinProbability * 100;
}

function betStatusLabel(report: IntelligenceReport | null, opp: Opportunity | null) {
  const raw = (report?.betStatus || opp?.sportsIntelligenceScore?.recommendation || "").toUpperCase();
  if (raw.includes("NO QUALIFIED BET")) return "PASS";
  if (raw.includes("INSUFFICIENT")) return "PASS";
  if (raw.includes("LEAN")) return "LEAN";
  if (raw.includes("STRONG") || raw.includes("ELITE")) return "STRONG BET";
  if (raw.includes("QUALIFIED")) return "BET";
  return "PASS";
}

function suggestedBetText(opp: Opportunity | null, bankroll: number | null) {
  if (!opp || opp.kelly20 == null) {
    return { headline: "Unavailable", detail: "Suggested bet size is not currently available." };
  }

  const pct = opp.kelly20 * 100;
  if (bankroll && bankroll > 0) {
    return {
      headline: `$${Math.round(bankroll * opp.kelly20).toLocaleString()}`,
      detail: `${pct.toFixed(1)}% of $${bankroll.toLocaleString()} bankroll`,
    };
  }

  return {
    headline: `${pct.toFixed(1)}% of bankroll`,
    detail: "Bankroll not set. Percentage sizing shown.",
  };
}

function edgeDirection(projection: GameProjection) {
  const points = projection.spreadAnalysis.edgePoints;
  const toward = points < 0 ? projection.awayTeam : projection.homeTeam;
  return {
    magnitude: Math.abs(points).toFixed(1),
    toward,
    signed: points.toFixed(1),
  };
}

function moveTheLineErrorMessage(error: unknown) {
  const fallback = "Move-the-Line is unavailable for this game right now.";
  if (!(error instanceof Error)) return fallback;
  const message = error.message.trim();
  return message || fallback;
}

export default function GameIntelligencePage() {
  const params = useParams<{ eventId: string }>();
  const searchParams = useSearchParams();
  const eventId = params.eventId;
  const presetAsk = searchParams.get("ask") || "";
  const snapshotId = searchParams.get("snapshotId") || undefined;

  const [projection, setProjection] = useState<GameProjection | null>(null);
  const [context, setContext] = useState<ScheduleContext | null>(null);
  const [opportunity, setOpportunity] = useState<Opportunity | null>(null);
  const [bestByMarket, setBestByMarket] = useState<Record<string, Opportunity>>({});
  const [intelligenceReport, setIntelligenceReport] = useState<IntelligenceReport | null>(null);
  const [weather, setWeather] = useState<WeatherStatus | null>(null);
  const [injury, setInjury] = useState<InjuryContext | null>(null);
  const [social, setSocial] = useState<SocialGameContext | null>(null);
  const [bankroll, setBankroll] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [added, setAdded] = useState(false);
  const [addToCardNotice, setAddToCardNotice] = useState("");
  const [askInput, setAskInput] = useState("");
  const [askMessages, setAskMessages] = useState<AskSiaMessage[]>([]);
  const [askLoading, setAskLoading] = useState(false);
  const [askError, setAskError] = useState("");
  const [presetAsked, setPresetAsked] = useState(false);
  const [moveSpread, setMoveSpread] = useState<number | null>(null);
  const [moveAssumedOdds, setMoveAssumedOdds] = useState<number | null>(null);
  const [moveResult, setMoveResult] = useState<MoveTheLineResult | null>(null);
  const [moveLoading, setMoveLoading] = useState(false);
  const [moveError, setMoveError] = useState("");

  useEffect(() => {
    if (!eventId) return;

    async function load() {
      try {
        setLoading(true);
        setError("");

        const proj = await fetchJson<GameProjection>(`/api/games/${eventId}`);
        setProjection(proj);

        const [ctxResult, oppResult, weatherResult, injuryResult, socialResult] = await Promise.allSettled([
          fetchJson<ScheduleContext>(`/api/games/${eventId}/context`),
          fetchJson<GameOpportunityResponse>(`/api/games/${eventId}/opportunity`),
          fetchJson<WeatherStatus>(`/api/games/${eventId}/weather`),
          fetchJson<{ injuryContext: InjuryContext }>(`/api/games/${eventId}/injuries`),
          fetchJson<SocialGameContext>(`/api/games/${eventId}/social-intelligence`),
        ]);

        if (ctxResult.status === "fulfilled") setContext(ctxResult.value);
        if (oppResult.status === "fulfilled") {
          setOpportunity(oppResult.value.opportunity);
          setBestByMarket(oppResult.value.bestByMarket ?? {});
          if (oppResult.value.intelligenceReport) setIntelligenceReport(oppResult.value.intelligenceReport);
          if (oppResult.value.opportunity?.market === "spread") {
            setMoveSpread(oppResult.value.opportunity.point);
            setMoveAssumedOdds(oppResult.value.opportunity.price);
          }
        }
        if (weatherResult.status === "fulfilled") setWeather(weatherResult.value);
        if (injuryResult.status === "fulfilled") setInjury(injuryResult.value.injuryContext);
        if (socialResult.status === "fulfilled") setSocial(socialResult.value);
      } catch (err) {
        const msg = err instanceof Error ? err.message : "";
        setError(msg.includes("404") ? "Game not found." : "Unable to load game intelligence.");
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, [eventId]);

  useEffect(() => {
    async function loadBankroll() {
      try {
        const token = localStorage.getItem("access_token");
        if (!token) return;
        const user = await fetchJson<CurrentUser>("/api/auth/me", {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (typeof user.bankroll === "number" && user.bankroll > 0) setBankroll(user.bankroll);
      } catch {
        setBankroll(null);
      }
    }

    void loadBankroll();
  }, []);

  async function handleAddToCard() {
    if (!opportunity) return;
    const result = await addToCardHelper(opportunity as Record<string, unknown>);
    setAdded(true);
    if (!result.success) {
      setAddToCardNotice("Added to My Card. Performance tracking could not be started right now.");
      return;
    }

    if (result.trackingStatus === "PARTIAL") {
      setAddToCardNotice(result.warning || "Added to My Card. Performance tracking could not be fully started.");
      return;
    }

    setAddToCardNotice("Added to My Card — tracking active.");
  }

  async function submitAsk(questionOverride?: string, moveTheLinePayload?: MoveTheLineResult | null) {
    if (!eventId) return;
    const question = (questionOverride ?? askInput).trim();
    if (!question) return;

    try {
      setAskLoading(true);
      setAskError("");
      const response = await fetchJson<AskSiaResponse>("/api/ask-sia", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ eventId, question, snapshotId, moveTheLine: moveTheLinePayload ?? undefined }),
      });

      setAskMessages((prev) => [...prev, { question, response }]);
      setAskInput("");
    } catch {
      setAskError("Ask SIA is unavailable right now.");
    } finally {
      setAskLoading(false);
    }
  }

  useEffect(() => {
    if (!presetAsk || presetAsked || loading || !eventId) return;
    setAskInput(presetAsk);
    void submitAsk(presetAsk);
    setPresetAsked(true);
  }, [eventId, loading, presetAsk, presetAsked]);

  async function runMoveTheLine(nextSpread?: number, nextOdds?: number) {
    if (!eventId || opportunity?.market !== "spread") return;
    const spreadToUse = nextSpread ?? moveSpread;
    const oddsToUse = nextOdds ?? moveAssumedOdds ?? opportunity.price;
    if (spreadToUse == null || oddsToUse == null) return;

    try {
      setMoveLoading(true);
      setMoveError("");
      const result = await fetchJson<MoveTheLineResult>("/api/move-the-line", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          eventId,
          hypotheticalSpread: spreadToUse,
          assumedOdds: oddsToUse,
          snapshotId,
        }),
      }, 20000);
      setMoveResult(result);
    } catch (error) {
      setMoveError(moveTheLineErrorMessage(error));
      setMoveResult(null);
    } finally {
      setMoveLoading(false);
    }
  }

  useEffect(() => {
    if (!eventId || loading) return;
    if (opportunity?.market !== "spread") return;
    if (moveSpread == null) return;
    void runMoveTheLine(moveSpread, moveAssumedOdds ?? opportunity.price);
  }, [eventId, loading, moveSpread, moveAssumedOdds, opportunity?.market, opportunity?.price]);

  const reasonSummary = useMemo(() => {
    if (intelligenceReport?.whySummary) return intelligenceReport.whySummary;
    if (opportunity?.sportsIntelligenceScore?.recommendation) {
      return `SIA's recommendation is ${opportunity.sportsIntelligenceScore.recommendation} based on model value and market context.`;
    }
    return "SIA currently does not have enough aligned edge to publish a qualified bet.";
  }, [intelligenceReport?.whySummary, opportunity?.sportsIntelligenceScore?.recommendation]);

  const whyFactors = useMemo(() => {
    if (!opportunity) {
      const reasons = intelligenceReport?.qualificationReasons ?? [];
      return reasons.slice(0, 3).map((r, idx) => `${idx + 1}. ${r}`);
    }

    const factors: string[] = [];
    const winPct = displayWinProbability(opportunity);
    const ev = opportunity.currentEV ?? opportunity.evPerDollar;
    factors.push(`Model vs Market: SIA probability ${Math.round(winPct ?? 0)}% vs market ${Math.round(opportunity.impliedProbability)}%.`);
    factors.push(`Price / Value: ${opportunity.pick} at ${signed(opportunity.price)} returns ${ev != null ? `+$${ev.toFixed(3)}` : "Unavailable"} EV per $1 (push-aware).`);
    factors.push(`Confidence: ${opportunity.confidence}/100 with market support ${opportunity.marketIntelligence.booksMoving}/${opportunity.marketIntelligence.booksTracked} books moving.`);
    if (opportunity.marketIntelligence.steamBooks > 0) {
      factors.push(`Supporting signal: ${opportunity.marketIntelligence.steamBooks} steam books aligned.`);
    }
    return factors.slice(0, 4);
  }, [intelligenceReport?.qualificationReasons, opportunity]);

  if (loading) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-5xl px-6 py-16 lg:px-10">
          <p className="text-sm text-zinc-500">Loading game intelligence...</p>
        </div>
      </main>
    );
  }

  if (error || !projection) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-5xl px-6 py-16 lg:px-10">
          <Link href="/games" className="text-sm text-zinc-500 hover:text-white">← Games</Link>
          <p className="mt-6 text-red-400">{error || "Game not found."}</p>
        </div>
      </main>
    );
  }

  const status = betStatusLabel(intelligenceReport, opportunity);
  const betSize = suggestedBetText(opportunity, bankroll);
  const hasContext = hasScheduleContext(context);
  const directionalEdge = edgeDirection(projection);
  const isPass = status === "PASS";
  const decisionHeadline = isPass ? (intelligenceReport?.currentLean || "NO LEAN") : (opportunity?.pick || intelligenceReport?.currentLean || "NO LEAN");
  const invalidationTrigger =
    opportunity?.truePlayableToReason ??
    intelligenceReport?.betTrigger?.message ??
    intelligenceReport?.qualificationReasons?.[0] ??
    "The market no longer offers enough edge at the current price.";
  const alternateMarketCards = ["spread", "moneyline", "total"]
    .map((marketKey) => ({ marketKey, item: bestByMarket[marketKey] ?? null }))
    .filter(({ marketKey, item }) => item != null && marketKey !== opportunity?.market);
  const quickPrompts = isPass
    ? [
        "Why isn't SIA betting this?",
        "What would make this qualify?",
        "Which side is closest?",
        "What is the biggest uncertainty?",
        "What changes SIA's mind?",
      ]
    : [
        "Why does SIA like this?",
        "What's the biggest risk?",
        "Is this still playable?",
        "Where should I bet it?",
        "What would make SIA pass?",
        "What is SIA seeing differently from the market?",
      ];

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-5xl px-6 py-10 lg:px-10 space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Link href="/games" className="text-sm text-zinc-500 transition hover:text-white">← Games</Link>
          <div className="flex gap-2">
            <a href="#ask-sia"><Button variant="outline" className="h-9 border-white/10 bg-transparent text-white hover:bg-white/[0.05]">ASK SIA</Button></a>
            <a href="#why"><Button variant="outline" className="h-9 border-white/10 bg-transparent text-white hover:bg-white/[0.05]">WHY?</Button></a>
            <a href="#advanced"><Button variant="outline" className="h-9 border-white/10 bg-transparent text-white hover:bg-white/[0.05]">ADVANCED</Button></a>
          </div>
        </div>

        <section className="rounded-3xl border border-white/[0.08] bg-[#0B1119] p-6 md:p-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm text-zinc-500">{projection.awayTeam} @ {projection.homeTeam}</p>
              <p className="mt-1 text-sm text-zinc-500">{formatKickoff(projection.commenceTime)}</p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Badge className="bg-white text-black hover:bg-zinc-100">SIA&apos;s TAKE</Badge>
              {opportunity?.sportsIntelligenceScore?.score != null && (
                <span className="text-sm font-semibold text-zinc-300">{opportunity.sportsIntelligenceScore.score.toFixed(1)} · {status}</span>
              )}
            </div>
          </div>

          <div className="mt-5 grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
            <div className="rounded-3xl border border-white/10 bg-white/[0.03] p-5 md:p-6">
              <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Decision</p>
              <div className="mt-3 flex flex-wrap items-baseline gap-3">
                <span className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-xs uppercase tracking-[0.2em] text-zinc-300">{status === "PASS" ? "PASS" : "BET"}</span>
                <h1 className="text-3xl font-semibold tracking-tight md:text-4xl">{decisionHeadline}</h1>
              </div>
              <p className="mt-4 max-w-2xl text-sm leading-6 text-zinc-300">{reasonSummary}</p>
              <p className="mt-3 text-xs uppercase tracking-[0.16em] text-zinc-600">Invalidation trigger</p>
              <p className="mt-1 text-sm text-zinc-400">{invalidationTrigger}</p>

              <div className="mt-5 grid gap-3 md:grid-cols-2">
                <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                  <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">SIA Projection</p>
                  <p className="mt-2 text-lg font-semibold">{projection.awayTeam} {projection.model.projectedScore.away.toFixed(1)} - {projection.homeTeam} {projection.model.projectedScore.home.toFixed(1)}</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                  <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Market</p>
                  <p className="mt-2 text-lg font-semibold">{projection.homeTeam} {signed(projection.market.homeSpread)} · O/U {projection.market.total.toFixed(1)}</p>
                  <p className="mt-1 text-xs text-zinc-500">Spread source: model feed market_home_spread for this game endpoint.</p>
                </div>
              </div>
            </div>

            <div className="rounded-3xl border border-white/10 bg-white/[0.03] p-5 md:p-6">
              <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Execution Panel</p>
              <div className="mt-4 space-y-3">
                <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                  <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Best Price</p>
                  <p className="mt-2 text-base font-semibold text-zinc-100">{formatBestPrice(opportunity)}</p>
                  <p className="mt-1 text-xs text-zinc-400">{opportunity?.book ?? "No current quote"}</p>
                </div>
                <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                  <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Playable To</p>
                  <p className="mt-2 text-base font-semibold text-zinc-100">{formatTruePlayableTo(opportunity)}</p>
                  <p className="mt-1 text-xs text-zinc-500">Uses true line-specific threshold only.</p>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                    <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Edge</p>
                    <p className="mt-2 text-base font-semibold text-zinc-100">{opportunity ? `${opportunity.edge.toFixed(1)} pts` : "Unavailable"}</p>
                    <p className="mt-1 text-xs text-zinc-500">SIA vs market.</p>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                    <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Confidence</p>
                    <p className="mt-2 text-base font-semibold text-zinc-100">{opportunity ? `${opportunity.confidence}/100` : "Unavailable"}</p>
                    <p className="mt-1 text-xs text-zinc-500">Model and market support.</p>
                  </div>
                </div>
                <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                  <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Suggested Bet</p>
                  <p className="mt-2 text-base font-semibold text-zinc-100">{betSize.headline}</p>
                  <p className="mt-1 text-xs text-zinc-500">{betSize.detail}</p>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-5 flex flex-wrap gap-3">
            <Button
              onClick={() => void handleAddToCard()}
              disabled={added || !opportunity}
              className={added ? "h-10 bg-emerald-400/10 text-emerald-300" : "h-10 bg-white text-black hover:bg-zinc-200"}
            >
              {added ? "Added to Card ✓" : "ADD TO CARD"}
            </Button>
            <a href="#why"><Button variant="outline" className="h-10 border-white/10 bg-transparent text-white hover:bg-white/[0.05]">WHY?</Button></a>
            <a href="#ask-sia"><Button variant="outline" className="h-10 border-white/10 bg-transparent text-white hover:bg-white/[0.05]">ASK SIA</Button></a>
            <a href="#advanced"><Button variant="outline" className="h-10 border-white/10 bg-transparent text-white hover:bg-white/[0.05]">ADVANCED</Button></a>
          </div>
          {addToCardNotice ? <p className="mt-3 text-sm text-zinc-400">{addToCardNotice}</p> : null}
        </section>

        <section id="ask-sia" className="rounded-3xl border border-white/[0.08] bg-[#0B1119] p-6 md:p-8">
          <p className="text-xs uppercase tracking-[0.2em] text-zinc-600">Ask SIA</p>
          <p className="mt-2 text-sm text-zinc-400">Complex Engine. Simple Answer.</p>

          <div className="mt-4 flex flex-wrap gap-2">
            {quickPrompts.map((prompt) => (
              <button
                key={prompt}
                className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs text-zinc-300 transition hover:bg-white/[0.08]"
                onClick={() => void submitAsk(prompt)}
                type="button"
              >
                {prompt}
              </button>
            ))}
          </div>

          <div className="mt-4 flex gap-2">
            <input
              value={askInput}
              onChange={(e) => setAskInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void submitAsk();
              }}
              placeholder="Ask about this game..."
              className="h-10 flex-1 rounded-xl border border-white/10 bg-black/20 px-3 text-sm text-white outline-none placeholder:text-zinc-600"
            />
            <Button
              onClick={() => void submitAsk()}
              disabled={askLoading || !askInput.trim()}
              className="h-10 bg-white text-black hover:bg-zinc-200"
            >
              {askLoading ? "Asking..." : "Ask"}
            </Button>
          </div>

          {askError && <p className="mt-3 text-sm text-rose-400">{askError}</p>}

          <div className="mt-5 space-y-4">
            {askMessages.map((item, idx) => (
              <div key={`${item.question}-${idx}`} className="rounded-2xl border border-white/10 bg-black/20 p-4">
                <p className="text-xs uppercase tracking-[0.16em] text-zinc-600">You asked</p>
                <p className="mt-1 text-sm text-zinc-200">{item.question}</p>

                <p className="mt-4 text-xs uppercase tracking-[0.16em] text-zinc-600">Answer</p>
                <p className="mt-1 text-sm text-zinc-100">{item.response.answer}</p>

                <p className="mt-3 text-xs uppercase tracking-[0.16em] text-zinc-600">Why</p>
                <div className="mt-1 space-y-1">
                  {item.response.why.map((line) => (
                    <p key={line} className="text-sm text-zinc-300">{line}</p>
                  ))}
                </div>

                <p className="mt-3 text-xs uppercase tracking-[0.16em] text-zinc-600">What Changes The Decision</p>
                <p className="mt-1 text-sm text-zinc-300">{item.response.whatChangesDecision}</p>

                {item.response.snapshotNote ? (
                  <p className="mt-3 text-xs text-zinc-500">{item.response.snapshotNote}</p>
                ) : null}

                {(item.response.missingData ?? []).length > 0 ? (
                  <div className="mt-3 space-y-1">
                    {(item.response.missingData ?? []).map((note) => (
                      <p key={note} className="text-xs text-zinc-500">{note}</p>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-3xl border border-white/[0.08] bg-[#0B1119] p-6 md:p-8">
          <p className="text-xs uppercase tracking-[0.2em] text-zinc-600">Research-only alternates</p>
          <p className="mt-2 text-sm text-zinc-400">These are supporting market views only. They are not presented as official SIA bets unless they are production eligible.</p>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {alternateMarketCards.length > 0 ? alternateMarketCards.map(({ marketKey, item }) => {
              const title = marketKey === "spread" ? "BEST SPREAD" : marketKey === "moneyline" ? "BEST MONEYLINE" : "BEST TOTAL";
              const isShadow = item.productionEligible === false;
              return (
                <div key={marketKey} className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                  <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">{title}</p>
                  <p className="mt-2 text-sm font-semibold text-zinc-100">{marketLabel(item)}</p>
                  <p className="mt-1 text-xs text-zinc-400">{item.book}</p>
                  <p className="mt-2 text-[11px] text-zinc-500">{isShadow ? "Shadow intelligence - not currently eligible for The SIA 3." : "Production-eligible market view."}</p>
                  <div className="mt-2 space-y-1 text-xs text-zinc-400">
                    <p>SIA probability: {item.currentWinProbability != null ? `${(item.currentWinProbability * 100).toFixed(1)}%` : `${item.modelProbability.toFixed(1)}%`}</p>
                    <p>Market probability: {item.impliedProbability.toFixed(1)}%</p>
                    <p>Edge: {item.edge.toFixed(1)} pts</p>
                    <p>EV: {item.currentEV != null ? `${item.currentEV >= 0 ? "+" : ""}${item.currentEV.toFixed(3)}` : "Unavailable"}</p>
                    <p>Playable-To: {formatTruePlayableTo(item)}</p>
                    <p>Qualification: {item.qualificationStatus ?? "UNKNOWN"}</p>
                  </div>
                </div>
              );
            }) : (
              <p className="text-sm text-zinc-500">No alternate market views are available right now.</p>
            )}
          </div>
        </section>

        <section id="move-the-line" className="rounded-3xl border border-white/[0.08] bg-[#0B1119] p-6 md:p-8">
          <p className="text-xs uppercase tracking-[0.2em] text-zinc-600">Move The Line</p>
          <p className="mt-2 text-sm text-zinc-400">Test a hypothetical spread using SIA's existing probability engine while holding price constant.</p>

          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Current Recommendation</p>
              <p className="mt-2 text-lg font-semibold">{opportunity ? `${opportunity.pick} (${signed(opportunity.price)})` : "Unavailable"}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">SIA Playable-To</p>
              <p className="mt-2 text-lg font-semibold">{opportunity?.truePlayableTo != null ? `${opportunity.pick.split(" ")[0]} ${formatSpread(opportunity.truePlayableTo)}` : "Unavailable"}</p>
            </div>
          </div>

          {opportunity?.market === "spread" ? (
            <>
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  className="h-10 border-white/10 bg-transparent text-white hover:bg-white/[0.05]"
                  onClick={() => {
                    if (moveSpread == null) return;
                    setMoveSpread(stepHalf(moveSpread, -0.5));
                  }}
                >
                  -
                </Button>
                <div className="min-w-[180px] rounded-xl border border-white/10 bg-black/20 px-4 py-2 text-center text-sm text-zinc-100">
                  {opportunity.pick.split(" ")[0]} {moveSpread != null ? formatSpread(moveSpread) : "--"}
                </div>
                <Button
                  type="button"
                  variant="outline"
                  className="h-10 border-white/10 bg-transparent text-white hover:bg-white/[0.05]"
                  onClick={() => {
                    if (moveSpread == null) return;
                    setMoveSpread(stepHalf(moveSpread, +0.5));
                  }}
                >
                  +
                </Button>

                <input
                  value={moveSpread == null ? "" : String(moveSpread)}
                  onChange={(e) => {
                    const parsed = Number.parseFloat(e.target.value);
                    if (Number.isNaN(parsed)) {
                      setMoveSpread(null);
                      return;
                    }
                    setMoveSpread(stepHalf(parsed, 0));
                  }}
                  placeholder="Direct spread"
                  className="h-10 w-32 rounded-xl border border-white/10 bg-black/20 px-3 text-sm text-white outline-none placeholder:text-zinc-600"
                />

                <Button
                  type="button"
                  className="h-10 bg-white text-black hover:bg-zinc-200"
                  onClick={() => void runMoveTheLine()}
                  disabled={moveLoading || moveSpread == null}
                >
                  {moveLoading ? "Updating..." : "Update"}
                </Button>
              </div>

              <div className="mt-4 rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Hypothetical Line</p>
                <p className="mt-2 text-sm text-zinc-300">{opportunity.pick.split(" ")[0]} {moveSpread != null ? formatSpread(moveSpread) : "--"}</p>
                <p className="mt-2 text-[10px] uppercase tracking-[0.18em] text-zinc-600">Price Assumption</p>
                <p className="mt-2 text-sm text-zinc-300">{signed(moveAssumedOdds ?? opportunity.price)} (held constant from current recommendation)</p>
                <p className="mt-2 text-xs text-zinc-500">
                  Move-the-Line holds the current price constant to isolate the effect of changing the spread. This does not represent a currently available sportsbook quote.
                </p>
              </div>

              {moveError ? <p className="mt-3 text-sm text-rose-400">{moveError}</p> : null}

              {moveResult ? (
                <div className="mt-4 space-y-4">
                  <div className={`rounded-2xl border p-4 ${moveResult.hypothetical.decisionStatus === "PLAYABLE" ? "border-emerald-400/30 bg-emerald-400/[0.06]" : "border-rose-400/30 bg-rose-400/[0.06]"}`}>
                    <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Decision Summary</p>
                    <p className="mt-2 text-sm text-zinc-100">{moveResult.hypothetical.decisionSummary}</p>
                    <p className="mt-2 text-xs text-zinc-300">Decision: {moveResult.hypothetical.decisionStatus}</p>
                    <p className="mt-1 text-xs text-zinc-300">Boundary: {moveResult.hypothetical.boundaryStatus}</p>
                    <p className="mt-1 text-xs text-zinc-300">{moveResult.hypothetical.statusReason}</p>
                  </div>

                  <div className="grid gap-3 md:grid-cols-2">
                    <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                      <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Current → Hypothetical</p>
                      <p className="mt-2 text-sm text-zinc-300">Line: {formatSpread(moveResult.current.spread)} → {formatSpread(moveResult.hypothetical.hypotheticalSpread)}</p>
                      <p className="mt-1 text-sm text-zinc-300">Win/Cover: {formatProbabilityUnit(moveResult.current.winProbability)} → {formatProbabilityUnit(moveResult.hypothetical.winProbability)}</p>
                      <p className="mt-1 text-sm text-zinc-300">Push: {formatProbabilityUnit(moveResult.current.pushProbability)} → {formatProbabilityUnit(moveResult.hypothetical.pushProbability)}</p>
                      <p className="mt-1 text-sm text-zinc-300">Push-aware EV: {formatEv(moveResult.current.pushAwareEV)} → {formatEv(moveResult.hypothetical.pushAwareEV)}</p>
                      <p className="mt-1 text-sm text-zinc-300">Original recommendation: {moveResult.current.recommendation}</p>
                      <p className="mt-1 text-sm text-zinc-300">Hypothetical decision: {moveResult.hypothetical.decisionStatus}</p>
                      <p className="mt-1 text-sm text-zinc-300">Hypothetical strength: {moveResult.hypothetical.recommendation}</p>
                    </div>

                    <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                      <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Value Lost vs Original</p>
                      <p className="mt-2 text-sm text-zinc-300">Cover probability: {moveResult.valueChange.probabilityChange != null ? `${(moveResult.valueChange.probabilityChange * 100).toFixed(1)} pts` : "Unavailable"}</p>
                      <p className="mt-1 text-sm text-zinc-300">EV: {moveResult.valueChange.evChange != null ? `${moveResult.valueChange.evChange >= 0 ? "+" : ""}$${moveResult.valueChange.evChange.toFixed(3)} per $1` : "Unavailable"}</p>
                      <p className="mt-1 text-sm text-zinc-300">Edge: {moveResult.valueChange.edgeChange != null ? `${(moveResult.valueChange.edgeChange * 100).toFixed(1)} pts` : "Unavailable"}</p>
                    </div>
                  </div>

                  <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                    <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Playable-To Visual</p>
                    <p className="mt-2 text-xs text-zinc-400">
                      BETTER PRICE {formatSpread((moveResult.current.spread ?? 0) + 1)} {formatSpread((moveResult.current.spread ?? 0) + 0.5)} {formatSpread(moveResult.current.spread ?? 0)} {formatSpread((moveResult.current.spread ?? 0) - 0.5)} {formatSpread((moveResult.current.spread ?? 0) - 1)} | {moveResult.hypothetical.truePlayableTo != null ? formatSpread(moveResult.hypothetical.truePlayableTo) : "N/A"} PLAYABLE TO
                    </p>
                  </div>

                  <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                    <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Ask SIA About This Line</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        type="button"
                        className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs text-zinc-300 transition hover:bg-white/[0.08]"
                        onClick={() => void submitAsk("Why is this still playable?", moveResult)}
                      >
                        Why is this still playable?
                      </button>
                      <button
                        type="button"
                        className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs text-zinc-300 transition hover:bg-white/[0.08]"
                        onClick={() => void submitAsk("How much value did I lose?", moveResult)}
                      >
                        How much value did I lose?
                      </button>
                      <button
                        type="button"
                        className="rounded-full border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs text-zinc-300 transition hover:bg-white/[0.08]"
                        onClick={() => void submitAsk("Why does this become a pass?", moveResult)}
                      >
                        Why does this become a pass?
                      </button>
                    </div>
                  </div>
                </div>
              ) : null}
            </>
          ) : (
            <p className="mt-4 text-sm text-zinc-500">Move-the-Line currently supports spread recommendations.</p>
          )}
        </section>

        <section id="why" className="rounded-3xl border border-white/[0.08] bg-[#0B1119] p-6 md:p-8">
          <p className="text-xs uppercase tracking-[0.2em] text-zinc-600">Why SIA Likes This</p>
          <div className="mt-4 space-y-2 text-sm text-zinc-300">
            {whyFactors.map((factor) => (
              <p key={factor}>{factor}</p>
            ))}
          </div>
          <div className="mt-5 rounded-2xl border border-amber-400/20 bg-amber-400/[0.05] p-4">
            <p className="text-[10px] uppercase tracking-[0.18em] text-amber-300">Biggest Risk</p>
            <p className="mt-2 text-sm text-amber-200">
              {intelligenceReport?.qualificationReasons?.[0] ?? "Market alignment can shift as prices, injuries, and weather update before kickoff."}
            </p>
          </div>
        </section>

        <section id="advanced" className="rounded-3xl border border-white/[0.08] bg-[#0B1119] p-6 md:p-8">
          <details>
            <summary className="cursor-pointer text-sm font-semibold tracking-wide text-zinc-200">ADVANCED INTELLIGENCE</summary>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">SIA vs Market</p>
                <p className="mt-2 text-sm text-zinc-300">{directionalEdge.magnitude} pts toward {directionalEdge.toward}</p>
                <p className="mt-1 text-xs text-zinc-500">Raw model edge points: {directionalEdge.signed}</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Probabilities</p>
                <p className="mt-2 text-sm text-zinc-300">SIA win probability: {opportunity && displayWinProbability(opportunity) != null ? `${Math.round(displayWinProbability(opportunity) as number)}%` : "Unavailable"}</p>
                <p className="mt-1 text-sm text-zinc-300">Push probability: {opportunity?.currentPushProbability != null ? `${(opportunity.currentPushProbability * 100).toFixed(1)}%` : "Unavailable"}</p>
                <p className="mt-1 text-sm text-zinc-300">Loss probability: {opportunity?.currentLossProbability != null ? `${(opportunity.currentLossProbability * 100).toFixed(1)}%` : "Unavailable"}</p>
                <p className="mt-1 text-sm text-zinc-300">Market implied: {opportunity ? `${Math.round(opportunity.impliedProbability)}%` : "Unavailable"}</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Value & Risk</p>
                <p className="mt-2 text-sm text-zinc-300">Push-aware EV: {opportunity?.currentEV != null ? `+$${opportunity.currentEV.toFixed(3)} per $1` : "Unavailable"}</p>
                <p className="mt-1 text-sm text-zinc-300">Confidence: {opportunity ? `${opportunity.confidence}/100` : "Unavailable"}</p>
                <p className="mt-1 text-sm text-zinc-300">Kelly (advanced): {opportunity ? `${(opportunity.kelly20 * 100).toFixed(1)}%` : "Unavailable"}</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Pricing Boundaries</p>
                <p className="mt-2 text-sm text-zinc-300">Fair line: {opportunity?.fairLine != null ? signed(opportunity.fairLine) : "Unavailable"}</p>
                <p className="mt-1 text-sm text-zinc-300">True Playable-To: {formatTruePlayableTo(opportunity)}</p>
                <p className="mt-1 text-sm text-zinc-300">Worst currently available playable price: {opportunity?.worstObservedPlayablePrice != null ? signed(opportunity.worstObservedPlayablePrice) : "Unavailable"}</p>
                <p className="mt-1 text-sm text-zinc-300">Playable-To EV floor: {opportunity?.minimumPlayableEV != null ? `${(opportunity.minimumPlayableEV * 100).toFixed(1)}%` : "Unavailable"}</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Market Intelligence</p>
                <p className="mt-2 text-sm text-zinc-300">Signal: {opportunity?.marketIntelligence.signal ?? "Unavailable"}</p>
                <p className="mt-1 text-sm text-zinc-300">Books moving: {opportunity ? `${opportunity.marketIntelligence.booksMoving}/${opportunity.marketIntelligence.booksTracked}` : "Unavailable"}</p>
                <p className="mt-1 text-sm text-zinc-300">Steam: {opportunity?.marketIntelligence.steamBooks ?? 0}</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Context</p>
                <p className="mt-2 text-sm text-zinc-300">Rest/Travel: {hasContext ? getRestLabel(context?.rest) : "Unavailable"}</p>
                <p className="mt-1 text-sm text-zinc-300">Travel miles: {formatTravelMiles(context?.travel) || "Unavailable"}</p>
                <p className="mt-1 text-sm text-zinc-300">Timezone shift: {formatTravelShift(context?.travel) || "Unavailable"}</p>
                <p className="mt-1 text-sm text-zinc-300">Injuries: {injury?.summary ?? "Unavailable"}</p>
                <p className="mt-1 text-sm text-zinc-300">Weather: {weather?.dataStatus ?? "Unavailable"}</p>
              </div>
              <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Social Intelligence</p>
                <p className="mt-2 text-sm text-zinc-300">{social?.summary ?? social?.reason ?? "Unavailable"}</p>
                <p className="mt-1 text-xs text-zinc-500">Provider: {social?.provider ?? "Unavailable"} · Status: {social?.dataStatus ?? "Unavailable"}</p>
                {(social?.keySignals ?? []).slice(0, 2).map((signal) => (
                  <p key={signal.signalId} className="mt-1 text-xs text-zinc-400">{signal.team} · {signal.category}: {signal.textSummary}</p>
                ))}
              </div>
            </div>
          </details>
        </section>
      </div>
    </main>
  );
}
