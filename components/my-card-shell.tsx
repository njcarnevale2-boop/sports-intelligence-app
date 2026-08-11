"use client";

import { useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import GameIntelligenceCard from "@/components/game-intelligence-card";
import { buildCardSummary, buildPortfolioRiskWarnings, createExportPayload, getEdgeValue, normalizeSavedBet, type RiskWarning, type SavedBet } from "@/lib/my-card-helpers";

const sportsbookOptions = ["DraftKings", "FanDuel", "BetMGM", "Caesars", "ESPN BET", "Fanatics", "bet365"];

function formatSigned(value: number) {
  return value >= 0 ? `+${value.toFixed(1)}` : value.toFixed(1);
}

export default function MyCardShell({ initialBets }: { initialBets: SavedBet[] }) {
  const [bets, setBets] = useState<SavedBet[]>(initialBets.map(normalizeSavedBet));
  const [selectedSportsbook, setSelectedSportsbook] = useState(sportsbookOptions[0]);
  const [reviewBet, setReviewBet] = useState<SavedBet | null>(initialBets[0] ? normalizeSavedBet(initialBets[0]) : null);

  const summary = useMemo(() => buildCardSummary(bets), [bets]);
  const warnings = useMemo(() => buildPortfolioRiskWarnings(bets), [bets]);

  const exportJson = () => {
    const payload = createExportPayload(bets);
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "my-card.json";
    link.click();
    URL.revokeObjectURL(url);
  };

  const exportCsv = () => {
    const rows = ["matchup,book,point,price,edge,evPerDollar,score\n", ...bets.map((bet) => `${bet.matchup},${bet.book},${bet.point ?? ""},${bet.price ?? ""},${getEdgeValue(bet.edge)},${bet.evPerDollar ?? ""},${bet.sportsIntelligenceScore?.score ?? ""}`)];
    const blob = new Blob(rows, { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "my-card.csv";
    link.click();
    URL.revokeObjectURL(url);
  };

  const exportPdf = () => {
    window.print();
  };

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-7xl px-6 py-10 lg:px-10">
        <section className="rounded-[32px] border border-white/[0.08] bg-[radial-gradient(circle_at_top_left,_rgba(16,185,129,0.18),_transparent_45%),linear-gradient(135deg,_rgba(255,255,255,0.04),_transparent)] p-8 shadow-2xl shadow-emerald-950/20">
          <div className="flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-[11px] uppercase tracking-[0.24em] text-emerald-400">My Card v2</p>
              <h1 className="mt-3 text-4xl font-semibold tracking-[-0.03em] md:text-6xl">Bet Card Command Center</h1>
              <p className="mt-4 max-w-3xl text-base leading-7 text-zinc-400">A Bloomberg-style operating desk for your active positions, sportsbook comparisons, and portfolio readiness.</p>
            </div>
            <div className="flex flex-wrap gap-3">
              <Button variant="outline" className="border-white/10 bg-white/[0.04] text-white hover:bg-white/[0.08]" onClick={exportJson}>Export JSON</Button>
              <Button variant="outline" className="border-white/10 bg-white/[0.04] text-white hover:bg-white/[0.08]" onClick={exportCsv}>Export CSV</Button>
              <Button variant="outline" className="border-white/10 bg-white/[0.04] text-white hover:bg-white/[0.08]" onClick={exportPdf}>Printable PDF</Button>
            </div>
          </div>

          <div className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-6">
            <div className="rounded-2xl border border-white/[0.08] bg-[#0D131C]/80 p-5">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600">Total Bets</p>
              <p className="mt-3 text-3xl font-semibold">{summary.totalBets}</p>
            </div>
            <div className="rounded-2xl border border-white/[0.08] bg-[#0D131C]/80 p-5">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600">Avg SI Score</p>
              <p className="mt-3 text-3xl font-semibold">{summary.averageSiScore}</p>
            </div>
            <div className="rounded-2xl border border-white/[0.08] bg-[#0D131C]/80 p-5">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600">Total EV</p>
              <p className="mt-3 text-3xl font-semibold text-emerald-400">+{summary.totalExpectedValue.toFixed(2)}</p>
            </div>
            <div className="rounded-2xl border border-white/[0.08] bg-[#0D131C]/80 p-5">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600">Bankroll Exposure</p>
              <p className="mt-3 text-3xl font-semibold">{summary.recommendedBankrollExposure.toFixed(2)}u</p>
            </div>
            <div className="rounded-2xl border border-white/[0.08] bg-[#0D131C]/80 p-5">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600">Portfolio Risk</p>
              <p className="mt-3 text-3xl font-semibold">{summary.portfolioRisk}</p>
            </div>
            <div className="rounded-2xl border border-white/[0.08] bg-[#0D131C]/80 p-5">
              <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600">Avg Edge</p>
              <p className="mt-3 text-3xl font-semibold text-emerald-400">{summary.averageEdge.toFixed(1)}%</p>
            </div>
          </div>
        </section>

        <section className="mt-8 grid gap-6 lg:grid-cols-[1.3fr_0.9fr]">
          <div className="rounded-[28px] border border-white/[0.08] bg-[#0D131C] p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[11px] uppercase tracking-[0.2em] text-zinc-600">Selected Opportunities</p>
                <h2 className="mt-2 text-2xl font-semibold">Active bet card</h2>
              </div>
              <Badge variant="outline" className="border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-400">Session persisted</Badge>
            </div>
            <div className="mt-6 space-y-4">
              {bets.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-white/[0.08] p-8 text-sm text-zinc-500">Add opportunities from the opportunities grid to populate the card.</div>
              ) : bets.map((bet) => (
                <GameIntelligenceCard
                  key={bet.id ?? `${bet.matchup}-${bet.book}`}
                  game={{
                    id: bet.id,
                    matchup: bet.matchup,
                    awayTeam: bet.awayTeam,
                    homeTeam: bet.homeTeam,
                    commenceTime: bet.commenceTime,
                    sportsIntelligenceScore: bet.sportsIntelligenceScore?.score,
                    marketGrade: bet.recommendation,
                    recommendation: bet.recommendation,
                    confidence: bet.confidence,
                    bestAvailableLine: `${bet.book} • ${bet.point ?? "—"}`,
                    expectedValue: bet.evPerDollar ? `+$${bet.evPerDollar.toFixed(2)} / $1` : "—",
                    weatherSummary: "Prepared for review in the hand-off view.",
                    injurySummary: bet.injuryContext?.summary ?? "Neutral",
                    topReasons: [bet.recommendation ?? "Model edge", `${bet.kelly20 ? `${bet.kelly20.toFixed(2)}u` : "—"} sizing`, `${bet.evPerDollar ? `+$${bet.evPerDollar.toFixed(2)}` : "—"} EV`],
                    evPerDollar: bet.evPerDollar,
                    book: bet.book,
                    market: bet.market,
                    pick: bet.pick,
                  }}
                  compact
                  clickable={false}
                  highlightElite={Boolean(bet.sportsIntelligenceScore?.score && bet.sportsIntelligenceScore.score >= 85)}
                />
              ))}
            </div>
          </div>

          <div className="space-y-6">
            <div className="rounded-[28px] border border-white/[0.08] bg-[#0D131C] p-6">
              <p className="text-[11px] uppercase tracking-[0.2em] text-zinc-600">Review Bet</p>
              <h2 className="mt-2 text-2xl font-semibold">Hand-off prep</h2>
              <div className="mt-4 rounded-2xl border border-white/[0.08] bg-black/20 p-4">
                <label className="text-sm text-zinc-500">Choose Sportsbook</label>
                <select value={selectedSportsbook} onChange={(event) => setSelectedSportsbook(event.target.value)} className="mt-2 w-full rounded-xl border border-white/[0.08] bg-[#05070A] px-3 py-2 text-sm text-white outline-none">
                  {sportsbookOptions.map((option) => <option key={option} value={option}>{option}</option>)}
                </select>
                <div className="mt-4 rounded-xl border border-emerald-400/15 bg-emerald-400/[0.05] p-4">
                  <p className="text-sm text-zinc-300">Prepared for {selectedSportsbook}</p>
                  <p className="mt-2 text-sm text-zinc-500">No bet is placed. This view prepares a clean hand-off package for later execution.</p>
                </div>
              </div>
            </div>

            <div className="rounded-[28px] border border-white/[0.08] bg-[#0D131C] p-6">
              <p className="text-[11px] uppercase tracking-[0.2em] text-zinc-600">Portfolio Intelligence</p>
              <div className="mt-4 space-y-3">
                {warnings.length === 0 ? (
                  <div className="rounded-2xl border border-emerald-400/15 bg-emerald-400/[0.05] p-4 text-sm text-emerald-400">Portfolio structure looks healthy.</div>
                ) : warnings.map((warning: RiskWarning) => (
                  <div key={warning.title} className={`rounded-2xl border p-4 ${warning.severity === "danger" ? "border-red-400/20 bg-red-400/[0.06] text-red-400" : "border-amber-400/20 bg-amber-400/[0.05] text-amber-400"}`}>
                    <p className="text-sm font-semibold">{warning.title}</p>
                    <p className="mt-1 text-sm">{warning.message}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="mt-8 rounded-[28px] border border-white/[0.08] bg-[#0D131C] p-6">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div>
              <p className="text-[11px] uppercase tracking-[0.2em] text-zinc-600">Best Sportsbook</p>
              <h2 className="mt-2 text-2xl font-semibold">Cross-book comparison</h2>
            </div>
          </div>
          <div className="mt-6 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="text-zinc-600">
                <tr>
                  <th className="px-3 py-3">Selection</th>
                  <th className="px-3 py-3">Best Line</th>
                  <th className="px-3 py-3">Best Odds</th>
                  <th className="px-3 py-3">Best EV</th>
                </tr>
              </thead>
              <tbody>
                {bets.map((bet) => (
                  <tr key={bet.id ?? `${bet.matchup}-${bet.book}`} className="border-t border-white/[0.06]">
                    <td className="px-3 py-3">{bet.matchup}</td>
                    <td className="px-3 py-3">{bet.pick}</td>
                    <td className="px-3 py-3">{bet.book}</td>
                    <td className="px-3 py-3 text-emerald-400">{bet.evPerDollar ? `+$${bet.evPerDollar.toFixed(2)}` : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
  );
}
