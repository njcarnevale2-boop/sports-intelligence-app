"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fetchJson } from "../../lib/api";
import { addToCard as addToCardHelper } from "@/lib/add-to-card";
import { formatKickoffLocal } from "@/app/lib/time-format";
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
  point: number;
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

function formatKickoff(iso: string) {
  return formatKickoffLocal(iso);
}

function signed(value: number) {
  return value > 0 ? `+${value}` : `${value}`;
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
  return signed(opp.truePlayableTo);
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

export default function GameIntelligencePage() {
  const params = useParams<{ eventId: string }>();
  const eventId = params.eventId;

  const [projection, setProjection] = useState<GameProjection | null>(null);
  const [context, setContext] = useState<ScheduleContext | null>(null);
  const [opportunity, setOpportunity] = useState<Opportunity | null>(null);
  const [intelligenceReport, setIntelligenceReport] = useState<IntelligenceReport | null>(null);
  const [weather, setWeather] = useState<WeatherStatus | null>(null);
  const [injury, setInjury] = useState<InjuryContext | null>(null);
  const [social, setSocial] = useState<SocialGameContext | null>(null);
  const [bankroll, setBankroll] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [added, setAdded] = useState(false);

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
          fetchJson<{ opportunity: Opportunity | null; intelligenceReport?: IntelligenceReport }>(`/api/games/${eventId}/opportunity`),
          fetchJson<WeatherStatus>(`/api/games/${eventId}/weather`),
          fetchJson<{ injuryContext: InjuryContext }>(`/api/games/${eventId}/injuries`),
          fetchJson<SocialGameContext>(`/api/games/${eventId}/social-intelligence`),
        ]);

        if (ctxResult.status === "fulfilled") setContext(ctxResult.value);
        if (oppResult.status === "fulfilled") {
          setOpportunity(oppResult.value.opportunity);
          if (oppResult.value.intelligenceReport) setIntelligenceReport(oppResult.value.intelligenceReport);
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
    if (result.success) setAdded(true);
  }

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
    factors.push(`Price / Value: ${opportunity.pick} at ${signed(opportunity.price)} returns +$${ev.toFixed(3)} EV per $1 (push-aware).`);
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

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-5xl px-6 py-10 lg:px-10 space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Link href="/games" className="text-sm text-zinc-500 transition hover:text-white">← Games</Link>
          <div className="flex gap-2">
            <a href="#why"><Button variant="outline" className="h-9 border-white/10 bg-transparent text-white hover:bg-white/[0.05]">WHY?</Button></a>
            <a href="#advanced"><Button variant="outline" className="h-9 border-white/10 bg-transparent text-white hover:bg-white/[0.05]">ADVANCED</Button></a>
          </div>
        </div>

        <section className="rounded-3xl border border-white/[0.08] bg-[#0B1119] p-6 md:p-8">
          <p className="text-sm text-zinc-500">{projection.awayTeam} @ {projection.homeTeam}</p>
          <p className="mt-1 text-sm text-zinc-500">{formatKickoff(projection.commenceTime)}</p>

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <Badge className="bg-white text-black hover:bg-zinc-100">{status === "PASS" ? "PASS" : "SIA PICK"}</Badge>
            {opportunity?.sportsIntelligenceScore?.score != null && (
              <span className="text-lg font-semibold text-zinc-200">{opportunity.sportsIntelligenceScore.score.toFixed(1)} · {status}</span>
            )}
          </div>

          <h1 className="mt-4 text-3xl font-semibold tracking-tight md:text-4xl">
            {status === "PASS" ? (intelligenceReport?.currentLean || "NO LEAN") : (opportunity?.pick || intelligenceReport?.currentLean || "NO LEAN")}
          </h1>

          <div className="mt-5 grid gap-3 md:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">SIA Projection</p>
              <p className="mt-2 text-lg font-semibold">{projection.awayTeam} {projection.model.projectedScore.away.toFixed(1)} - {projection.homeTeam} {projection.model.projectedScore.home.toFixed(1)}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Market</p>
              <p className="mt-2 text-lg font-semibold">{projection.homeTeam} {signed(projection.market.homeSpread)} · O/U {projection.market.total.toFixed(1)}</p>
              <p className="mt-1 text-xs text-zinc-500">Spread source: model feed market_home_spread for this game endpoint.</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Best Price</p>
              <p className="mt-2 text-lg font-semibold">{formatBestPrice(opportunity)}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Playable To</p>
              <p className="mt-2 text-lg font-semibold">{formatTruePlayableTo(opportunity)}</p>
              <p className="mt-1 text-xs text-zinc-500">Uses true line-specific threshold only.</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Suggested Bet</p>
              <p className="mt-2 text-lg font-semibold">{betSize.headline}</p>
              <p className="mt-1 text-xs text-zinc-500">{betSize.detail}</p>
            </div>
          </div>

          <div className="mt-4 rounded-2xl border border-white/10 bg-white/[0.03] p-4">
            <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">Why SIA Likes It</p>
            <p className="mt-2 text-sm text-zinc-300 leading-6">{reasonSummary}</p>
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
            <a href="#advanced"><Button variant="outline" className="h-10 border-white/10 bg-transparent text-white hover:bg-white/[0.05]">ADVANCED</Button></a>
          </div>
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
                <p className="mt-1 text-sm text-zinc-300">Minimum required EV: {opportunity?.minimumPlayableEV != null ? `${(opportunity.minimumPlayableEV * 100).toFixed(1)}%` : "Unavailable"}</p>
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
