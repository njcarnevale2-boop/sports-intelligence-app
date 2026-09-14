"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchJson } from "../lib/api";
import { trackAnalyticsEvent } from "../lib/analytics";

type LedgerWager = {
  wagerId: string;
  placedAtUTC: string;
  eventId: string;
  commenceTime?: string | null;
  awayTeam?: string | null;
  homeTeam?: string | null;
  market?: string | null;
  side?: string | null;
  sportsbook?: string | null;
  line?: number | null;
  americanOdds?: number | null;
  amountRisked?: number | null;
  unitsRisked?: number | null;
  unitSizeAtBet?: number | null;
  decisionId?: string | null;
  sourceSnapshotId?: string | null;
  siaConfidenceScore?: number | null;
  siaTier?: string | null;
  modelProbabilityAtBet?: number | null;
  calibratedProbabilityAtBet?: number | null;
  impliedProbabilityAtBet?: number | null;
  edgeAtBet?: number | null;
  evAtBet?: number | null;
  openingLine?: number | null;
  recommendationLine?: number | null;
  closingLine?: number | null;
  closingPrice?: number | null;
  clvPoints?: number | null;
  result: "PENDING" | "WIN" | "LOSS" | "PUSH";
  amountWonLost?: number | null;
  unitsWonLost?: number | null;
  settledAtUTC?: string | null;
};

type PersonalLedgerResponse = {
  startingBankroll: number;
  unitSize: number;
  currentBankroll: number;
  totalPL: number;
  totalUnits: number;
  wins: number;
  losses: number;
  pushes: number;
  roi?: number | null;
  pendingExposure: number;
  averageClvPoints?: number | null;
  unknownStakeCount?: number;
  unknownStakePendingCount?: number;
  unknownStakeSettledCount?: number;
  count: number;
  pendingCount: number;
  settledCount: number;
  wagers: LedgerWager[];
};

function money(value: number): string {
  return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pct(value: number | null | undefined): string {
  if (value == null) return "-";
  return `${(value * 100).toFixed(2)}%`;
}

function signed(value: number | null | undefined, digits = 2): string {
  if (value == null) return "-";
  return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
}

function fmtLine(value: number | null | undefined): string {
  if (value == null) return "-";
  return value > 0 ? `+${value}` : `${value}`;
}

function statusClass(status: LedgerWager["result"]): string {
  if (status === "WIN") return "text-emerald-300 border-emerald-400/25 bg-emerald-400/10";
  if (status === "LOSS") return "text-rose-300 border-rose-400/25 bg-rose-400/10";
  if (status === "PUSH") return "text-amber-300 border-amber-400/25 bg-amber-400/10";
  return "text-zinc-300 border-white/15 bg-white/5";
}

function asPercentMaybe(value: number | null | undefined): string {
  if (value == null) return "-";
  const normalized = value > 1 ? value / 100 : value;
  return `${(normalized * 100).toFixed(1)}%`;
}

export default function MyCardPage() {
  const [data, setData] = useState<PersonalLedgerResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    void trackAnalyticsEvent("MyCardViewed", { page: "my-card" });
  }, []);

  useEffect(() => {
    async function loadLedger() {
      try {
        const response = await fetchJson<PersonalLedgerResponse>("/api/recommendation/my-card-ledger");
        setData(response);
        setError("");
      } catch (err) {
        console.error(err);
        setError("Unable to load personal wager ledger.");
      } finally {
        setLoading(false);
      }
    }

    void loadLedger();
  }, []);

  const wagers = useMemo(() => data?.wagers ?? [], [data]);
  const settledCount = data?.settledCount ?? 0;

  if (loading) {
    return <main className="min-h-screen bg-[#070A0F] p-8 text-zinc-200">Loading personal ledger...</main>;
  }

  if (error) {
    return <main className="min-h-screen bg-[#070A0F] p-8 text-rose-300">{error}</main>;
  }

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-7xl px-6 py-10 lg:px-10">
        <section className="rounded-[28px] border border-white/[0.08] bg-[#0D131C] p-6">
          <p className="text-[11px] uppercase tracking-[0.22em] text-emerald-400">My Card</p>
          <h1 className="mt-2 text-4xl font-semibold tracking-[-0.02em]">Personal Betting Ledger</h1>

          <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <Metric label="Starting Bankroll" value={money(data?.startingBankroll ?? 1000)} />
            <Metric label="Current Bankroll" value={money(data?.currentBankroll ?? 1000)} />
            <Metric label="Total P/L" value={signed(data?.totalPL, 2)} tone={Number(data?.totalPL ?? 0) >= 0 ? "good" : "bad"} />
            <Metric label="Total Units" value={signed(data?.totalUnits, 2)} tone={Number(data?.totalUnits ?? 0) >= 0 ? "good" : "bad"} />
          </div>
        </section>

        <section className="mt-6 rounded-[28px] border border-white/[0.08] bg-[#0D131C] p-6">
          <p className="text-[11px] uppercase tracking-[0.2em] text-zinc-500">Record</p>
          <div className="mt-4 grid gap-4 md:grid-cols-3 xl:grid-cols-6">
            <Metric label="W-L-P" value={`${data?.wins ?? 0}-${data?.losses ?? 0}-${data?.pushes ?? 0}`} />
            <Metric label="ROI" value={pct(data?.roi)} />
            <Metric label="Pending Exposure" value={money(data?.pendingExposure ?? 0)} />
            <Metric label="Average CLV" value={data?.averageClvPoints == null ? "-" : `${signed(data.averageClvPoints, 3)} pts`} />
            <Metric label="Settled Wagers" value={`${settledCount}`} />
            <Metric label="Pending Wagers" value={`${data?.pendingCount ?? 0}`} />
          </div>
        </section>

        <section className="mt-6 rounded-[28px] border border-white/[0.08] bg-[#0D131C] p-6">
          <div className="flex items-center justify-between">
            <p className="text-[11px] uppercase tracking-[0.2em] text-zinc-500">Wagers</p>
            <p className="text-xs text-zinc-400">{data?.count ?? 0} total</p>
          </div>

          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="text-zinc-500">
                <tr>
                  <th className="px-2 py-2">Matchup</th>
                  <th className="px-2 py-2">Selection</th>
                  <th className="px-2 py-2">Book</th>
                  <th className="px-2 py-2">Line/Odds</th>
                  <th className="px-2 py-2">Amount</th>
                  <th className="px-2 py-2">Units</th>
                  <th className="px-2 py-2">SIA</th>
                  <th className="px-2 py-2">Status</th>
                  <th className="px-2 py-2">P/L</th>
                  <th className="px-2 py-2">CLV</th>
                </tr>
              </thead>
              <tbody>
                {wagers.map((wager) => (
                  <tr key={wager.wagerId} className="border-t border-white/[0.06]">
                    <td className="px-2 py-2">{(wager.awayTeam && wager.homeTeam) ? `${wager.awayTeam} @ ${wager.homeTeam}` : wager.eventId}</td>
                    <td className="px-2 py-2">{`${wager.market ?? ""} ${wager.side ?? ""}`.trim() || "-"}</td>
                    <td className="px-2 py-2">{wager.sportsbook || "-"}</td>
                    <td className="px-2 py-2">{`${fmtLine(wager.line)} / ${fmtLine(wager.americanOdds)}`}</td>
                    <td className="px-2 py-2">{wager.amountRisked == null ? "Stake unknown" : money(wager.amountRisked)}</td>
                    <td className="px-2 py-2">{wager.unitsRisked == null ? "Stake unknown" : wager.unitsRisked.toFixed(2)}</td>
                    <td className="px-2 py-2">{`${wager.siaTier ?? "-"} ${wager.siaConfidenceScore != null ? `(${wager.siaConfidenceScore.toFixed(1)})` : ""}`.trim()}</td>
                    <td className="px-2 py-2">
                      <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] ${statusClass(wager.result)}`}>{wager.result}</span>
                    </td>
                    <td className="px-2 py-2">{wager.result === "PENDING" ? "-" : signed(wager.amountWonLost, 2)}</td>
                    <td className="px-2 py-2">{wager.clvPoints == null ? "-" : `${signed(wager.clvPoints, 3)} pts`}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {wagers.length === 0 ? (
            <p className="mt-4 text-sm text-zinc-400">No tracked wagers yet. Add bets from Opportunities to start ledger tracking.</p>
          ) : null}

          {wagers.length > 0 ? (
            <div className="mt-4 text-xs text-zinc-500">
              <p>Model probability at bet time is preserved immutably for every wager.</p>
              <p>Pending wagers are not included in bankroll P/L.</p>
              {(data?.unknownStakeCount ?? 0) > 0 ? (
                <p>
                  {(data?.unknownStakeCount ?? 0).toString()} legacy wager
                  {(data?.unknownStakeCount ?? 0) === 1 ? "" : "s"} have unknown stake sizing and are excluded from financial metrics.
                </p>
              ) : null}
            </div>
          ) : null}
        </section>
      </div>
    </main>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" }) {
  const toneClass = tone === "good" ? "text-emerald-300" : tone === "bad" ? "text-rose-300" : "text-white";
  return (
    <div className="rounded-2xl border border-white/[0.08] bg-black/20 p-4">
      <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-500">{label}</p>
      <p className={`mt-2 text-2xl font-semibold ${toneClass}`}>{value}</p>
    </div>
  );
}