"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import TeamLogo from "@/components/team-logo";
import Tooltip from "@/components/ui/tooltip";
import { fetchJson } from "../lib/api";
import { addToCard as addToCardHelper } from "@/lib/add-to-card";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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

type SIScore = {
  score: number;
  grade: string;
  recommendation: string;
  reasons: string[];
};

type InjuryCtx = {
  awayTeam?: string;
  homeTeam?: string;
  awayInjuryScore?: number;
  homeInjuryScore?: number;
  healthierTeam?: string;
  severity?: string;
  summary?: string;
  providerMetadata?: { isLive?: boolean; dataStatus?: string };
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
  edge: number;
  evPerDollar: number;
  kelly20: number;
  recommendation: string;
  confidence: number;
  rank: number;
  sportsIntelligenceScore: SIScore;
  marketIntelligence: MarketIntelligence;
  injuryContext?: InjuryCtx | null;
};

type GameInfo = {
  eventId: string;
  week: number;
  awayTeam: string;
  homeTeam: string;
  awayLogo?: string;
  homeLogo?: string;
};

type OppsResponse = { opportunities: Opportunity[] };
type GamesResponse = { availableWeeks: number[]; games: GameInfo[] };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatKickoff(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "TBD";
  return d.toLocaleString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

function signedOdds(n: number): string {
  return n > 0 ? `+${n}` : `${n}`;
}

function scoreTone(s: number): string {
  if (s >= 85) return "text-emerald-400";
  if (s >= 75) return "text-sky-400";
  return "text-amber-400";
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function BriefingPage() {
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [gameMap, setGameMap] = useState<Map<string, GameInfo>>(new Map());
  const [currentWeek, setCurrentWeek] = useState<number>(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [addedId, setAddedId] = useState<string | null>(null);
  const [snapshotMsg, setSnapshotMsg] = useState("");

  useEffect(() => {
    async function load() {
      try {
        const [gamesResult, oppsResult] = await Promise.allSettled([
          fetchJson<GamesResponse>("/api/games?week=1"),
          fetchJson<OppsResponse>("/api/opportunities?limit=100&week=1"),
        ]);

        if (gamesResult.status === "fulfilled") {
          const { games, availableWeeks } = gamesResult.value;
          setCurrentWeek(availableWeeks[0] ?? 1);
          const map = new Map<string, GameInfo>();
          for (const g of games) map.set(g.eventId, g);
          setGameMap(map);
        }

        if (oppsResult.status === "fulfilled") {
          setOpportunities(oppsResult.value.opportunities);
        } else {
          setError("Unable to load briefing.");
        }
      } catch {
        setError("Unable to load briefing.");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, []);

  // One opportunity per game, filtered to current week only
  const topPerGame = useMemo(() => {
    const seen = new Set<string>();
    return opportunities.filter((o) => {
      // When gameMap is loaded, only show games from the current week
      if (gameMap.size > 0 && !gameMap.has(o.eventId)) return false;
      if (seen.has(o.eventId)) return false;
      seen.add(o.eventId);
      return true;
    });
  }, [opportunities, gameMap]);

  const lead = topPerGame[0];
  const next = topPerGame.slice(1, 5);

  // Market watch: real signals from market intelligence data
  const marketSignals = useMemo(() => {
    const signals: string[] = [];
    for (const opp of topPerGame.slice(0, 15)) {
      const mi = opp.marketIntelligence;
      if (!mi) continue;
      if (mi.steamBooks >= 2) {
        signals.push(
          `${opp.awayTeam} @ ${opp.homeTeam}: Steam — ${mi.steamBooks} books moved on ${opp.pick}`
        );
      } else if (mi.largestPointMove >= 1.0) {
        signals.push(
          `${opp.awayTeam} @ ${opp.homeTeam}: Line moved ${mi.largestPointMove.toFixed(1)} pts on ${opp.pick}`
        );
      } else if (mi.largestPriceMove >= 15) {
        signals.push(
          `${opp.awayTeam} @ ${opp.homeTeam}: Price moved ${mi.largestPriceMove.toFixed(0)} on ${opp.pick}`
        );
      }
      if (signals.length >= 3) break;
    }
    return signals;
  }, [topPerGame]);

  // Key context: meaningful injury alerts (moderate+ severity only)
  const contextAlerts = useMemo(() => {
    const alerts: string[] = [];
    for (const opp of topPerGame) {
      const ic = opp.injuryContext;
      if (!ic?.summary) continue;
      const sev = ic.severity?.toLowerCase() ?? "";
      if (["moderate", "significant", "high", "severe"].includes(sev)) {
        alerts.push(`${opp.awayTeam} @ ${opp.homeTeam}: ${ic.summary}`);
      }
      if (alerts.length >= 3) break;
    }
    return alerts;
  }, [topPerGame]);

  // Logo + full name lookups from games API
  function awayLogo(o: Opportunity) { return gameMap.get(o.eventId)?.awayLogo; }
  function homeLogo(o: Opportunity) { return gameMap.get(o.eventId)?.homeLogo; }
  function awayName(o: Opportunity) { return gameMap.get(o.eventId)?.awayTeam ?? o.awayTeam; }
  function homeName(o: Opportunity) { return gameMap.get(o.eventId)?.homeTeam ?? o.homeTeam; }

  async function handleAddToCard(opp: Opportunity) {
    setSnapshotMsg("");
    const result = await addToCardHelper(opp as Record<string, unknown>);
    setAddedId(opp.id);
    setSnapshotMsg(
      result.success
        ? "Added to My Card — tracking active."
        : "Added to My Card, but performance tracking could not start."
    );
  }

  // ---------------------------------------------------------------------------
  // Loading / error
  // ---------------------------------------------------------------------------

  if (loading) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-4xl px-6 py-16 lg:px-10">
          <p className="text-sm text-zinc-500">Building briefing…</p>
        </div>
      </main>
    );
  }

  if (error || !lead) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-4xl px-6 py-16 lg:px-10">
          <p className="text-red-400">{error || "No qualifying opportunities this week."}</p>
        </div>
      </main>
    );
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-4xl space-y-8 px-4 py-10 sm:px-6 lg:px-8">

        {/* ── HEADER ──────────────────────────────────────────────────────── */}
        <header>
          <p className="text-[10px] uppercase tracking-[0.28em] text-zinc-600">Sports Intelligence</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight sm:text-4xl">
            Week {currentWeek} Briefing
          </h1>
          <p className="mt-2 text-sm text-zinc-500">
            What the model wants you to know about this week&apos;s NFL slate.
          </p>
        </header>

        {/* ── A. LEAD OPPORTUNITY ─────────────────────────────────────────── */}
        <section className="rounded-2xl border border-emerald-400/15 bg-emerald-400/[0.03] p-6 sm:p-8">
          <p className="text-[10px] uppercase tracking-[0.24em] text-emerald-500">Lead Opportunity</p>

          {/* Teams */}
          <div className="mt-5 flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <TeamLogo src={awayLogo(lead)} alt={awayName(lead)} size={40} />
              <span className="text-sm font-medium text-zinc-300">{awayName(lead)}</span>
            </div>
            <span className="text-zinc-700 text-sm">@</span>
            <div className="flex items-center gap-2">
              <TeamLogo src={homeLogo(lead)} alt={homeName(lead)} size={40} />
              <span className="text-sm font-medium text-zinc-300">{homeName(lead)}</span>
            </div>
          </div>

          <p className="mt-2 text-xs text-zinc-600">{formatKickoff(lead.commenceTime)}</p>

          {/* The Bet */}
          <div className="mt-4">
            <h2 className="text-3xl font-semibold sm:text-4xl">{lead.pick}</h2>
            <p className="mt-1 text-sm text-zinc-500">
              {lead.book} · {signedOdds(lead.price)}
            </p>
          </div>

          {/* Key Metrics */}
          <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-xl border border-white/[0.07] bg-black/20 p-3">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600 inline-flex items-center">SI Score<Tooltip term="SI Score" /></p>
              <p className={`mt-1 text-xl font-semibold ${scoreTone(lead.sportsIntelligenceScore.score)}`}>
                {lead.sportsIntelligenceScore.score.toFixed(1)}
              </p>
            </div>
            <div className="rounded-xl border border-white/[0.07] bg-black/20 p-3">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600 inline-flex items-center">Model Edge<Tooltip term="Model Edge" /></p>
              <p className="mt-1 text-xl font-semibold text-emerald-400">+{lead.edge.toFixed(1)}%</p>
            </div>
            <div className="rounded-xl border border-white/[0.07] bg-black/20 p-3">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600 inline-flex items-center">EV / $1<Tooltip term="EV" /></p>
              <p className="mt-1 text-xl font-semibold">+${lead.evPerDollar.toFixed(3)}</p>
            </div>
            <div className="rounded-xl border border-white/[0.07] bg-black/20 p-3">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600 inline-flex items-center">Confidence<Tooltip term="Confidence" /></p>
              <p className="mt-1 text-xl font-semibold">{lead.confidence}%</p>
            </div>
          </div>

          {/* Why SIA likes it */}
          {lead.sportsIntelligenceScore.reasons?.[0] ? (
            <p className="mt-4 text-sm leading-6 text-zinc-400">
              {lead.sportsIntelligenceScore.reasons[0]}
            </p>
          ) : (
            <p className="mt-4 text-sm leading-6 text-zinc-400">
              Model probability {lead.modelProbability.toFixed(1)}% vs market implied{" "}
              {lead.impliedProbability.toFixed(1)}% — {lead.edge.toFixed(1)}% edge with{" "}
              {lead.confidence}% confidence.
            </p>
          )}

          {/* Actions */}
          <div className="mt-5 flex flex-wrap gap-3">
            <Link
              href={`/games/${lead.eventId}`}
              className="inline-flex h-10 items-center rounded-lg bg-white px-5 text-sm font-medium text-black transition hover:bg-zinc-200"
            >
              View Game Intelligence
            </Link>
            <button
              onClick={() => void handleAddToCard(lead)}
              disabled={addedId === lead.id}
              className={`inline-flex h-10 items-center rounded-lg border px-5 text-sm font-medium transition ${
                addedId === lead.id
                  ? "border-emerald-400/20 bg-emerald-400/[0.08] text-emerald-300"
                  : "border-white/10 bg-transparent text-zinc-300 hover:bg-white/[0.05]"
              }`}
            >
              {addedId === lead.id ? "Added ✓" : "Add to My Card"}
            </button>
          </div>
          {snapshotMsg && (
            <p className="mt-2 text-xs text-zinc-500">{snapshotMsg}</p>
          )}
        </section>

        {/* ── B. NEXT BEST ────────────────────────────────────────────────── */}
        {next.length > 0 && (
          <section>
            <div className="mb-3 flex items-center justify-between">
              <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">Next Best Opportunities</p>
              <Link href="/opportunities" className="text-xs text-zinc-600 transition hover:text-white">
                Full board →
              </Link>
            </div>

            <div className="space-y-2">
              {next.map((opp) => (
                <article
                  key={opp.id}
                  className="rounded-xl border border-white/[0.07] bg-[#0B1119] px-4 py-3"
                >
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                    {/* Teams + bet */}
                    <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-5">
                      <div className="flex items-center gap-2 flex-wrap">
                        <TeamLogo src={awayLogo(opp)} alt={awayName(opp)} size={28} />
                        <span className="text-xs text-zinc-400">{awayName(opp)}</span>
                        <span className="text-zinc-700 text-xs">@</span>
                        <TeamLogo src={homeLogo(opp)} alt={homeName(opp)} size={28} />
                        <span className="text-xs text-zinc-400">{homeName(opp)}</span>
                      </div>
                      <div>
                        <p className="text-sm font-semibold">{opp.pick}</p>
                        <p className="text-[11px] text-zinc-600">{opp.book} · {formatKickoff(opp.commenceTime)}</p>
                      </div>
                    </div>

                    {/* Metrics + action */}
                    <div className="flex items-center gap-4 sm:shrink-0">
                      <div className="flex gap-3 text-xs">
                        <span className={`font-semibold ${scoreTone(opp.sportsIntelligenceScore.score)}`}>
                          SI {opp.sportsIntelligenceScore.score.toFixed(0)}
                        </span>
                        <span className="text-emerald-400">+{opp.edge.toFixed(1)}%</span>
                        <span className="text-zinc-600">{opp.confidence}%</span>
                      </div>
                      <Link
                        href={`/games/${opp.eventId}`}
                        className="shrink-0 rounded-lg border border-white/10 px-3 py-1.5 text-xs font-medium text-zinc-400 transition hover:border-white/20 hover:text-white"
                      >
                        View →
                      </Link>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </section>
        )}

        {/* ── C. MARKET WATCH ─────────────────────────────────────────────── */}
        <section className="rounded-2xl border border-white/[0.07] bg-[#0B1119] p-6">
          <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">Market Watch</p>
          {marketSignals.length > 0 ? (
            <ul className="mt-4 space-y-3">
              {marketSignals.map((sig, i) => (
                <li key={i} className="flex items-start gap-3 text-sm text-zinc-400">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-amber-400" />
                  {sig}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-4 text-sm text-zinc-600">No major market signals detected.</p>
          )}
        </section>

        {/* ── D. KEY GAME CONTEXT ─────────────────────────────────────────── */}
        <section className="rounded-2xl border border-white/[0.07] bg-[#0B1119] p-6">
          <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">Key Game Context</p>
          {contextAlerts.length > 0 ? (
            <ul className="mt-4 space-y-3">
              {contextAlerts.map((alert, i) => (
                <li key={i} className="flex items-start gap-3 text-sm text-zinc-400">
                  <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-red-400" />
                  {alert}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-4 text-sm text-zinc-600">No major injury or weather alerts.</p>
          )}
        </section>

      </div>
    </main>
  );
}
