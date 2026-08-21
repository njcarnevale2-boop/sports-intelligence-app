"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import FreshnessBadge from "@/components/ui/freshness-badge";
import { fetchJson } from "./lib/api";
import { trackAnalyticsEvent } from "./lib/analytics";

type QuoteWarnings = {
  isStale?: boolean;
  limitedDepth?: boolean;
};

type DecisionBoardItem = {
  rank: number;
  eventId: string;
  marketFamily: string;
  selection: string;
  line: number | null;
  price: number | null;
  sportsbook: string | null;
  bestAvailableLine: number | null;
  bestAvailablePrice: number | null;
  bestAvailableSportsbook: string | null;
  playableTo: number | null;
  modelProbability: number | null;
  marketImpliedProbability: number | null;
  edge: number | null;
  expectedValue: number | null;
  confidence: number | null;
  marketDepth: string;
  quoteFreshness: string;
  gameStartTime: string;
  recommendationStatus: string;
  productionEligible: boolean;
  whySiaLikesIt: string;
  riskFactors: string[];
  invalidationReason?: string | null;
  quoteWarnings?: QuoteWarnings;
};

type NoBetState = {
  headline: string;
  summary: string;
  closestOpportunity?: {
    eventId?: string;
    selection?: string;
    distanceFromTrigger?: string | null;
  } | null;
};

type DecisionBoardResponse = {
  week?: number;
  dataStatus?: string;
  lastUpdated?: string | null;
  snapshotId?: string;
  decisionBoard: DecisionBoardItem[];
  count: number;
  officialMarketsDisplayed: string[];
  noBetState?: NoBetState | null;
  crossMarketComparable: boolean;
  universalSia3: string;
};

function formatSigned(value: number | null | undefined) {
  if (value == null) return "Unavailable";
  return value > 0 ? `+${value}` : `${value}`;
}

function formatPercent(value: number | null | undefined) {
  if (value == null) return "Unavailable";
  const pct = value <= 1.0 ? value * 100 : value;
  return `${pct.toFixed(1)}%`;
}

function depthLabel(depth: string) {
  const normalized = String(depth || "").toUpperCase();
  if (normalized === "DEEP") return "DEEP MARKET DEPTH";
  if (normalized === "MODERATE") return "MODERATE MARKET DEPTH";
  if (normalized === "THIN" || normalized === "SINGLE_BOOK") return "LIMITED MARKET DEPTH";
  return "MARKET DATA LIMITED";
}

function freshnessLabel(freshness: string) {
  const normalized = String(freshness || "").toUpperCase();
  if (normalized === "FRESH") return "FRESH";
  if (normalized === "WARM") return "RECENT";
  if (normalized === "STALE") return "STALE — VERIFY BEFORE BETTING";
  return "QUOTE FRESHNESS UNKNOWN";
}

function executableQuote(item: DecisionBoardItem) {
  const line = item.line != null ? formatSigned(item.line) : null;
  const price = item.price != null ? formatSigned(item.price) : null;
  const book = item.sportsbook || "Unavailable";
  if (line && price) return `${line} (${price}) · ${book}`;
  if (price) return `${price} · ${book}`;
  if (line) return `${line} · ${book}`;
  return `Unavailable · ${book}`;
}

export default function Home() {
  const [board, setBoard] = useState<DecisionBoardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        setError("");
        void trackAnalyticsEvent("DecisionBoardViewed", { page: "home" });
        const payload = await fetchJson<DecisionBoardResponse>("/api/decision-board?limit=3");
        setBoard(payload);
      } catch (err) {
        console.error(err);
        setError("Unable to load SIA decision board.");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, []);

  const items = board?.decisionBoard || [];
  const title = useMemo(() => {
    if (items.length === 0) return "No High-Conviction Bets";
    if (items.length === 1) return "Top Opportunity";
    return "Top Opportunities";
  }, [items.length]);

  if (loading) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:px-10">
          <p className="text-sm text-zinc-500">Loading SIA decision board...</p>
        </div>
      </main>
    );
  }

  if (error || !board) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:px-10">
          <p className="text-sm text-rose-400">{error || "Unable to load decision board."}</p>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <header className="border-b border-white/[0.06]">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5 lg:px-10">
          <div>
            <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-zinc-600">SIA</p>
            <h1 className="mt-1 text-xl font-semibold tracking-tight">AI Sports Betting Intelligence</h1>
          </div>
          <div className="flex items-center gap-3">
            {board.dataStatus ? <FreshnessBadge status={board.dataStatus} lastUpdated={board.lastUpdated} label="Market" /> : null}
            <Link href="/games">
              <Button variant="outline" className="h-10 border-white/10 bg-transparent text-white hover:bg-white/[0.05]">Games Hub</Button>
            </Link>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-6xl px-6 py-8 lg:px-10">
        <section className="rounded-3xl border border-white/[0.08] bg-[#0B1119] p-6 md:p-8">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-zinc-600">Decision Board</p>
              <h2 className="mt-2 text-3xl font-semibold tracking-tight md:text-4xl">{title}</h2>
              <p className="mt-2 text-sm text-zinc-500">
                {board.week != null ? `Week ${board.week}` : "Current slate"} · Official markets: {board.officialMarketsDisplayed.join(", ") || "NONE"}
              </p>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <Badge variant="outline" className="border-white/[0.08] bg-white/[0.03] text-zinc-300">{items.length} Official Picks</Badge>
              <Badge variant="outline" className="border-white/[0.08] bg-white/[0.03] text-zinc-300">Universal SIA3 {board.universalSia3}</Badge>
            </div>
          </div>

          {items.length === 0 ? (
            <div className="mt-6 rounded-2xl border border-dashed border-white/[0.1] p-5 text-zinc-300">
              <p className="text-sm font-semibold">{board.noBetState?.headline || "NO HIGH-CONVICTION BETS RIGHT NOW"}</p>
              <p className="mt-2 text-sm text-zinc-400">{board.noBetState?.summary || "SIA does not currently have a production-qualified edge at available prices."}</p>
              {board.noBetState?.closestOpportunity ? (
                <div className="mt-4 rounded-xl border border-white/[0.08] bg-black/20 p-4 text-sm">
                  <p className="text-zinc-500">Watching</p>
                  <p className="mt-1 text-zinc-100">{board.noBetState.closestOpportunity.selection || "Closest setup"}</p>
                  {board.noBetState.closestOpportunity.distanceFromTrigger ? (
                    <p className="mt-1 text-zinc-400">{board.noBetState.closestOpportunity.distanceFromTrigger}</p>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="mt-6 grid gap-4 lg:grid-cols-3">
              {items.map((item) => (
                <article key={`${item.eventId}-${item.rank}`} className="rounded-2xl border border-white/[0.08] bg-black/20 p-5">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-600">#{item.rank}</p>
                  <h3 className="mt-2 text-2xl font-semibold text-white">{item.selection}</h3>
                  <p className="mt-1 text-sm text-zinc-300">{item.marketFamily} · {item.recommendationStatus}</p>

                  <div className="mt-4 space-y-2 text-sm">
                    <p className="text-zinc-400">
                      <span className="text-zinc-500">BEST AVAILABLE:</span> <span className="text-zinc-200">{executableQuote(item)}</span>
                    </p>
                    <p className="text-zinc-400">
                      <span className="text-zinc-500">PLAYABLE TO:</span> <span className="text-zinc-200">{item.playableTo != null ? formatSigned(item.playableTo) : "Unavailable"}</span>
                    </p>
                    <p className="text-zinc-400">
                      <span className="text-zinc-500">SIA EDGE:</span> <span className="text-zinc-200">{item.edge != null ? `${item.edge.toFixed(1)} pts` : "Unavailable"}</span>
                    </p>
                    <p className="text-zinc-400">
                      <span className="text-zinc-500">CONFIDENCE:</span> <span className="text-zinc-200">{item.confidence != null ? `${item.confidence}/100` : "Unavailable"}</span>
                    </p>
                    <p className="text-zinc-400">
                      <span className="text-zinc-500">SIA VS MARKET:</span> <span className="text-zinc-200">{formatPercent(item.modelProbability)} vs {formatPercent(item.marketImpliedProbability)}</span>
                    </p>
                    <p className="text-zinc-400">
                      <span className="text-zinc-500">QUOTE:</span> <span className="text-zinc-200">{freshnessLabel(item.quoteFreshness)}</span>
                    </p>
                    <p className="text-zinc-400">
                      <span className="text-zinc-500">DEPTH:</span> <span className="text-zinc-200">{depthLabel(item.marketDepth)}</span>
                    </p>
                  </div>

                  <div className="mt-4 rounded-xl border border-white/[0.08] bg-white/[0.03] p-3">
                    <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-600">Why SIA Likes It</p>
                    <p className="mt-2 text-sm text-zinc-300 leading-6">{item.whySiaLikesIt}</p>
                  </div>

                  <div className="mt-4 rounded-xl border border-amber-400/20 bg-amber-400/[0.04] p-3">
                    <p className="text-[10px] uppercase tracking-[0.16em] text-amber-300">What Could Change This</p>
                    <p className="mt-2 text-sm text-amber-200">{item.invalidationReason || item.riskFactors[0] || "Material market movement can invalidate this opportunity."}</p>
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2">
                    <Link href={`/games/${item.eventId}`}>
                      <Button className="h-9 bg-white px-4 text-black hover:bg-zinc-200">GAME INTEL</Button>
                    </Link>
                    <Link href={`/games/${item.eventId}?ask=${encodeURIComponent("Why does SIA like this bet?")}`}>
                      <Button variant="outline" className="h-9 border-white/10 bg-transparent px-4 text-white hover:bg-white/[0.05]">ASK SIA</Button>
                    </Link>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
