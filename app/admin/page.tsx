"use client";

import { useEffect, useState } from "react";

import { fetchJson } from "../lib/api";
import { Button } from "@/components/ui/button";

type SchedulerStatus = {
  lastRefreshAt?: string | null;
  nextRefreshAt?: string | null;
  cadenceMinutes?: number | null;
  isRunning?: boolean;
  lastError?: string | null;
  consecutiveFailures?: number;
  quotaRemaining?: number | null;
  quotaPaused?: boolean;
  provider?: string;
  closingLinesCapturedThisRun?: number;
  closingLinesStillPending?: number;
  closingLinesMissing?: number;
};

type AdminStatus = {
  apiHealth: string;
  lastRefresh: string;
  refreshDuration: number;
  gamesLoaded: number;
  opportunitiesLoaded: number;
  injuriesLoaded: number;
  weatherLoaded: number;
  databaseStatus: string;
  queueStatus: string;
  providerMetadata?: {
    injury?: { provider?: string; lastUpdated?: string; isLive?: boolean; status?: string };
    weather?: { provider?: string; lastUpdated?: string; isLive?: boolean; status?: string };
    odds?: { provider?: string; lastUpdated?: string; isLive?: boolean; status?: string };
    social?: { provider?: string; lastUpdated?: string; isLive?: boolean; status?: string };
  };
  errorLog: Array<{ timestamp: string; message: string }>;
  // Live odds fields
  oddsProvider?: string;
  oddsDataStatus?: string;
  lastLiveOddsRefresh?: string | null;
  oddsGamesUpdated?: number;
  snapshotCount?: number;
  apiUsageRemaining?: number | null;
  // Scheduler
  scheduler?: SchedulerStatus;
  // CLV / closing line
  closingLinesCaptured?: number;
  pendingClosingLines?: number;
  missingClosingLines?: number;
  averageCLV?: number | null;
  // Injury status
  injuryProvider?: string;
  injuryIsLive?: boolean;
  injuryDataStatus?: string;
  lastInjuryRefresh?: string | null;
  injuryPlayersTracked?: number;
  injuryTeamsUpdated?: number;
  lastInjuryError?: string | null;
  // Social status
  socialProvider?: string;
  socialIsLive?: boolean;
  socialDataStatus?: string;
  socialSourcesActive?: number;
  socialSignalsDetected?: number;
  socialCorroboratedSignals?: number;
  socialOfficialSignals?: number;
  lastSocialIngestion?: string | null;
  lastSocialError?: string | null;
  socialCoveragePercent?: number;
  socialTeamsComplete?: number;
  socialTeamsPartial?: number;
  socialTeamsMissing?: number;
  socialQueriesExecuted?: number;
  socialPostsRead?: number;
  // Weather status
  weatherProvider?: string;
  weatherIsLive?: boolean;
  weatherDataStatus?: string;
  lastWeatherRefresh?: string | null;
  weatherGamesUpdated?: number;
  weatherForecastsAvailable?: number;
  lastWeatherError?: string | null;
  // Decision ledger status
  ledgerDecisionsRecorded?: number;
  ledgerOfficialPublications?: number;
  ledgerLatestPublication?: { publicationId?: string; publishedAtUTC?: string } | null;
  ledgerIntegrity?: { valid?: boolean; invalidHashCount?: number } | null;
  ledgerOutcomesCaptured?: number;
  ledgerClosingLinesCaptured?: number;
  ledgerMissingOutcomes?: number;
  ledgerMissingClosingLines?: number;
  ledgerAuditRows?: Array<{
    timestamp?: string;
    week?: string;
    rank?: number | null;
    selection?: string;
    line?: number | null;
    price?: number | null;
    sportsbook?: string | null;
    siScore?: number | null;
    ev?: number | null;
    decisionHash?: string;
    result?: string | null;
  }>;
};

type SocialCoverageTeam = {
  team: string;
  sourcesActive: number;
  verifiedSources: number;
  tier1: number;
  tier2: number;
  tier3: number;
  coverageStatus: "COMPLETE" | "PARTIAL" | "MISSING";
};

type SocialCoverageResponse = {
  teamsCovered: number;
  teamsComplete: number;
  teamsPartial: number;
  teamsMissing: number;
  totalSources: number;
  verifiedSources: number;
  coveragePercent: number;
  teams: SocialCoverageTeam[];
};

const metricCard = (label: string, value: string | number, accent = "text-white") => (
  <div className="rounded-2xl border border-white/10 bg-[#0B1119] p-5">
    <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">{label}</p>
    <p className={`mt-2 text-2xl font-semibold ${accent}`}>{value}</p>
  </div>
);

export default function AdminPage() {
  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [socialCoverage, setSocialCoverage] = useState<SocialCoverageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadStatus = async () => {
    try {
      setLoading(true);
      try {
        const [payload, coverage] = await Promise.all([
          fetchJson<AdminStatus>("/api/admin/status"),
          fetchJson<SocialCoverageResponse>("/api/admin/social-sources/coverage"),
        ]);
        setStatus(payload);
        setSocialCoverage(coverage);
      } catch {
        setStatus({
          apiHealth: "degraded",
          lastRefresh: "n/a",
          refreshDuration: 0,
          gamesLoaded: 0,
          opportunitiesLoaded: 0,
          injuriesLoaded: 0,
          weatherLoaded: 0,
          databaseStatus: "disconnected",
          queueStatus: "idle",
          errorLog: [{ timestamp: new Date().toISOString(), message: "Unable to fetch admin status" }],
        });
        setSocialCoverage(null);
      }
    } catch (error) {
      console.error(error);
      setStatus({
        apiHealth: "degraded",
        lastRefresh: "n/a",
        refreshDuration: 0,
        gamesLoaded: 0,
        opportunitiesLoaded: 0,
        injuriesLoaded: 0,
        weatherLoaded: 0,
        databaseStatus: "disconnected",
        queueStatus: "idle",
        errorLog: [{ timestamp: new Date().toISOString(), message: "Unable to fetch admin status" }],
      });
      setSocialCoverage(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await fetchJson("/api/admin/refresh", { method: "POST" });
      await loadStatus();
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-7xl px-6 py-10 lg:px-10">
        <div className="flex flex-col gap-4 border-b border-white/10 pb-6 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Operations Center</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">Admin Dashboard</h1>
            <p className="mt-2 max-w-2xl text-sm text-zinc-500">Monitor the platform health, refresh cadence, and the current data state from a single control surface.</p>
          </div>
          <Button onClick={handleRefresh} disabled={refreshing} className="h-11 bg-white px-5 text-black hover:bg-zinc-200">
            {refreshing ? "Refreshing..." : "Refresh Data"}
          </Button>
        </div>

        {loading ? (
          <div className="mt-8 rounded-2xl border border-white/10 bg-[#0B1119] p-10 text-sm text-zinc-400">Loading admin metrics...</div>
        ) : status ? (
          <>
            <section className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              {metricCard("API Health", status.apiHealth === "healthy" ? "Healthy" : "Degraded", status.apiHealth === "healthy" ? "text-emerald-400" : "text-amber-400")}
              {metricCard("Last Refresh", status.lastRefresh.slice(0, 19).replace("T", " "))}
              {metricCard("Refresh Duration", `${status.refreshDuration.toFixed(2)}s`)}
              {metricCard("Database", status.databaseStatus)}
            </section>

            <section className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              {metricCard("Games Loaded", status.gamesLoaded)}
              {metricCard("Opportunities Loaded", status.opportunitiesLoaded)}
              {metricCard("Injuries Loaded", status.injuriesLoaded)}
              {metricCard("Weather Loaded", status.weatherLoaded)}
            </section>

            <section className="mt-6 grid gap-6 lg:grid-cols-[1.25fr_0.75fr]">
              <div className="rounded-3xl border border-white/10 bg-[#0B1119] p-6">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold">System Status</h2>
                  <span className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-xs text-emerald-400">{status.queueStatus}</span>
                </div>
                <div className="mt-6 space-y-3 text-sm text-zinc-400">
                  <div className="flex items-center justify-between rounded-xl border border-white/10 bg-black/20 px-4 py-3"><span>API health</span><span className="font-medium text-white">{status.apiHealth}</span></div>
                  <div className="flex items-center justify-between rounded-xl border border-white/10 bg-black/20 px-4 py-3"><span>Database</span><span className="font-medium text-white">{status.databaseStatus}</span></div>
                  <div className="flex items-center justify-between rounded-xl border border-white/10 bg-black/20 px-4 py-3"><span>Queue</span><span className="font-medium text-white">{status.queueStatus}</span></div>
                </div>

                <div className="mt-6">
                  <h3 className="text-sm font-semibold text-white">Provider Health</h3>
                  <div className="mt-3 space-y-2">
                    {Object.entries(status.providerMetadata ?? {}).map(([key, entry]) => (
                      <div key={key} className="flex items-center justify-between rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                        <div>
                          <p className="font-medium text-white">{key}</p>
                          <p className="text-zinc-500">{entry?.provider ?? "Mock"}</p>
                        </div>
                        <div className="text-right">
                          <p className={`text-sm ${entry?.status === "Live" ? "text-emerald-400" : entry?.status === "Unavailable" ? "text-amber-400" : "text-sky-400"}`}>
                            {entry?.status ?? (entry?.isLive ? "Live" : "Mock")}
                          </p>
                          <p className="text-xs text-zinc-500">{entry?.lastUpdated ? new Date(entry.lastUpdated).toLocaleString() : "n/a"}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="rounded-3xl border border-white/10 bg-[#0B1119] p-6">
                <h2 className="text-lg font-semibold">Recent Errors</h2>
                <div className="mt-4 space-y-3">
                  {status.errorLog.slice(0, 10).map((entry, index) => (
                    <div key={`${entry.timestamp}-${index}`} className="rounded-xl border border-white/10 bg-black/20 p-3 text-sm">
                      <p className="text-zinc-500">{entry.timestamp}</p>
                      <p className="mt-1 text-zinc-300">{entry.message}</p>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            <section className="mt-6 rounded-3xl border border-white/10 bg-[#0B1119] p-6">
              <h2 className="text-lg font-semibold">Live Odds Status</h2>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Odds Provider</p>
                  <p className="mt-1 font-medium text-white">{status.oddsProvider ?? "The Odds API"}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Odds Data Status</p>
                  <p className={`mt-1 font-medium ${status.oddsDataStatus === "LIVE" ? "text-emerald-400" : status.oddsDataStatus === "STALE" ? "text-amber-400" : "text-zinc-400"}`}>
                    {status.oddsDataStatus ?? "UNAVAILABLE"}
                  </p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Last Live Odds Refresh</p>
                  <p className="mt-1 font-medium text-white">
                    {status.lastLiveOddsRefresh ? new Date(status.lastLiveOddsRefresh).toLocaleString() : "n/a"}
                  </p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Games Updated</p>
                  <p className="mt-1 font-medium text-white">{status.oddsGamesUpdated ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Snapshot Count</p>
                  <p className="mt-1 font-medium text-white">{status.snapshotCount?.toLocaleString() ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">API Usage Remaining</p>
                  <p className={`mt-1 font-medium ${(status.apiUsageRemaining ?? 0) > 100 ? "text-emerald-400" : (status.apiUsageRemaining ?? 0) > 20 ? "text-amber-400" : "text-red-400"}`}>
                    {status.apiUsageRemaining != null ? status.apiUsageRemaining : "n/a"}
                  </p>
                </div>
              </div>
            </section>

            {status.scheduler && (
              <section className="mt-6 rounded-3xl border border-white/10 bg-[#0B1119] p-6">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold">Refresh Scheduler</h2>
                  <span className={`rounded-full border px-3 py-1 text-xs ${
                    status.scheduler.isRunning
                      ? "border-sky-400/20 bg-sky-400/10 text-sky-400"
                      : status.scheduler.quotaPaused
                        ? "border-amber-400/20 bg-amber-400/10 text-amber-400"
                        : "border-emerald-400/20 bg-emerald-400/10 text-emerald-400"
                  }`}>
                    {status.scheduler.isRunning ? "Running" : status.scheduler.quotaPaused ? "Paused (quota)" : "Idle"}
                  </span>
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                    <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Last Refresh</p>
                    <p className="mt-1 font-medium text-white">
                      {status.scheduler.lastRefreshAt ? new Date(status.scheduler.lastRefreshAt).toLocaleString() : "Never"}
                    </p>
                  </div>
                  <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                    <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Next Refresh</p>
                    <p className="mt-1 font-medium text-white">
                      {status.scheduler.quotaPaused
                        ? "Suspended"
                        : status.scheduler.nextRefreshAt
                          ? new Date(status.scheduler.nextRefreshAt).toLocaleString()
                          : "Pending"}
                    </p>
                  </div>
                  <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                    <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Refresh Frequency</p>
                    <p className="mt-1 font-medium text-white">
                      {status.scheduler.cadenceMinutes != null
                        ? `Every ${status.scheduler.cadenceMinutes} min`
                        : "Paused"}
                    </p>
                  </div>
                  <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                    <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Provider</p>
                    <p className="mt-1 font-medium text-white">{status.scheduler.provider ?? "The Odds API"}</p>
                  </div>
                  <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                    <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Consecutive Failures</p>
                    <p className={`mt-1 font-medium ${(status.scheduler.consecutiveFailures ?? 0) > 0 ? "text-amber-400" : "text-emerald-400"}`}>
                      {status.scheduler.consecutiveFailures ?? 0}
                    </p>
                  </div>
                  <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                    <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Last Error</p>
                    <p className="mt-1 text-xs font-medium text-amber-400 break-words">
                      {status.scheduler.lastError ?? "None"}
                    </p>
                  </div>
                </div>
                {/* Per-run CLV stats */}
                <div className="mt-3 grid gap-3 sm:grid-cols-3">
                  <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                    <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Captured This Run</p>
                    <p className="mt-1 font-medium text-emerald-400">{status.scheduler.closingLinesCapturedThisRun ?? 0}</p>
                  </div>
                  <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                    <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Still Pending</p>
                    <p className="mt-1 font-medium text-sky-400">{status.scheduler.closingLinesStillPending ?? 0}</p>
                  </div>
                  <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                    <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Missing This Run</p>
                    <p className="mt-1 font-medium text-amber-400">{status.scheduler.closingLinesMissing ?? 0}</p>
                  </div>
                </div>
              </section>
            )}

            <section className="mt-6 rounded-3xl border border-white/10 bg-[#0B1119] p-6">
              <h2 className="text-lg font-semibold">Closing Line Value (CLV)</h2>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Closing Lines Captured</p>
                  <p className="mt-1 font-medium text-emerald-400">{status.closingLinesCaptured ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Pending</p>
                  <p className="mt-1 font-medium text-sky-400">{status.pendingClosingLines ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Missing / Not Captured</p>
                  <p className="mt-1 font-medium text-amber-400">{status.missingClosingLines ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Average CLV (pts)</p>
                  <p className={`mt-1 font-medium ${(status.averageCLV ?? 0) > 0 ? "text-emerald-400" : (status.averageCLV ?? 0) < 0 ? "text-red-400" : "text-zinc-400"}`}>
                    {status.averageCLV != null ? (status.averageCLV > 0 ? `+${status.averageCLV}` : status.averageCLV) : "—"}
                  </p>
                </div>
              </div>
            </section>

            <section className="mt-6 rounded-3xl border border-white/10 bg-[#0B1119] p-6">
              <h2 className="text-lg font-semibold">Decision Ledger Audit</h2>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">2026 Decisions Recorded</p>
                  <p className="mt-1 font-medium text-white">{status.ledgerDecisionsRecorded ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Official SIA 3 Publications</p>
                  <p className="mt-1 font-medium text-white">{status.ledgerOfficialPublications ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Outcomes Captured</p>
                  <p className="mt-1 font-medium text-emerald-400">{status.ledgerOutcomesCaptured ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Closing Lines Captured</p>
                  <p className="mt-1 font-medium text-emerald-400">{status.ledgerClosingLinesCaptured ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Missing Outcomes</p>
                  <p className="mt-1 font-medium text-amber-400">{status.ledgerMissingOutcomes ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Missing Closing Lines</p>
                  <p className="mt-1 font-medium text-amber-400">{status.ledgerMissingClosingLines ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm sm:col-span-2">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Ledger Integrity</p>
                  <p className={`mt-1 font-medium ${status.ledgerIntegrity?.valid ? "text-emerald-400" : "text-amber-400"}`}>
                    {status.ledgerIntegrity?.valid ? "VALID" : "CHECK REQUIRED"}
                  </p>
                  <p className="text-[11px] text-zinc-500">Invalid hashes: {status.ledgerIntegrity?.invalidHashCount ?? 0}</p>
                </div>
              </div>

              <div className="mt-6 overflow-x-auto rounded-2xl border border-white/10">
                <table className="min-w-full divide-y divide-white/10 text-left text-xs">
                  <thead className="bg-black/30 text-zinc-400 uppercase tracking-widest">
                    <tr>
                      <th className="px-3 py-2">Timestamp</th>
                      <th className="px-3 py-2">Week</th>
                      <th className="px-3 py-2">Rank</th>
                      <th className="px-3 py-2">Selection</th>
                      <th className="px-3 py-2">Line</th>
                      <th className="px-3 py-2">Price</th>
                      <th className="px-3 py-2">Sportsbook</th>
                      <th className="px-3 py-2">SI</th>
                      <th className="px-3 py-2">EV</th>
                      <th className="px-3 py-2">Hash</th>
                      <th className="px-3 py-2">Result</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5 text-zinc-200">
                    {(status.ledgerAuditRows ?? []).slice(0, 50).map((row, idx) => (
                      <tr key={`${row.decisionHash}-${idx}`}>
                        <td className="px-3 py-2">{row.timestamp ? new Date(row.timestamp).toLocaleString() : "n/a"}</td>
                        <td className="px-3 py-2">{row.week ?? "n/a"}</td>
                        <td className="px-3 py-2">{row.rank ?? "-"}</td>
                        <td className="px-3 py-2">{row.selection ?? "n/a"}</td>
                        <td className="px-3 py-2">{row.line ?? "-"}</td>
                        <td className="px-3 py-2">{row.price ?? "-"}</td>
                        <td className="px-3 py-2">{row.sportsbook ?? "-"}</td>
                        <td className="px-3 py-2">{row.siScore ?? "-"}</td>
                        <td className="px-3 py-2">{row.ev ?? "-"}</td>
                        <td className="px-3 py-2 font-mono text-[10px] text-zinc-400">{(row.decisionHash ?? "").slice(0, 12)}</td>
                        <td className="px-3 py-2">{row.result ?? "-"}</td>
                      </tr>
                    ))}
                    {(status.ledgerAuditRows ?? []).length === 0 && (
                      <tr>
                        <td className="px-3 py-4 text-zinc-500" colSpan={11}>No ledger rows captured yet.</td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="mt-6 rounded-3xl border border-white/10 bg-[#0B1119] p-6">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">Social Intelligence Status</h2>
                <span className={`rounded-full border px-3 py-1 text-xs ${
                  status.socialDataStatus === "LIVE"
                    ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-400"
                    : status.socialDataStatus === "MOCK"
                      ? "border-amber-400/20 bg-amber-400/10 text-amber-400"
                      : "border-zinc-700 bg-zinc-800 text-zinc-400"
                }`}>
                  {status.socialDataStatus ?? "MOCK"}
                </span>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Social Provider</p>
                  <p className="mt-1 font-medium text-white">{status.socialProvider ?? "MOCK"}</p>
                  <p className="text-[10px] text-zinc-600">{status.socialIsLive ? "Live" : "Mock ingestion only"}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Last Ingestion</p>
                  <p className="mt-1 font-medium text-white">
                    {status.lastSocialIngestion ? new Date(status.lastSocialIngestion).toLocaleString() : "n/a"}
                  </p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Sources Active</p>
                  <p className="mt-1 font-medium text-white">{status.socialSourcesActive ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Signals Detected</p>
                  <p className="mt-1 font-medium text-white">{status.socialSignalsDetected ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Corroborated Signals</p>
                  <p className="mt-1 font-medium text-sky-400">{status.socialCorroboratedSignals ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Official Signals</p>
                  <p className="mt-1 font-medium text-emerald-400">{status.socialOfficialSignals ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Coverage</p>
                  <p className="mt-1 font-medium text-white">{status.socialCoveragePercent != null ? `${status.socialCoveragePercent}%` : "0%"}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Queries Prepared</p>
                  <p className="mt-1 font-medium text-white">{status.socialQueriesExecuted ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Posts Read</p>
                  <p className="mt-1 font-medium text-white">{status.socialPostsRead ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm col-span-full">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Last Error</p>
                  <p className="mt-1 text-xs font-medium text-amber-400 break-words">
                    {status.lastSocialError ?? "None"}
                  </p>
                </div>
              </div>
            </section>

            <section className="mt-6 rounded-3xl border border-white/10 bg-[#0B1119] p-6">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h2 className="text-lg font-semibold">Social Sources</h2>
                  <p className="mt-1 text-sm text-zinc-500">Internal coverage tracking for future real NFL source onboarding.</p>
                </div>
                <div className="text-right text-sm text-zinc-400">
                  <p>{socialCoverage?.teamsCovered ?? 0} teams represented</p>
                  <p>{socialCoverage?.coveragePercent ?? 0}% coverage</p>
                </div>
              </div>

              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Complete</p>
                  <p className="mt-1 font-medium text-emerald-400">{socialCoverage?.teamsComplete ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Partial</p>
                  <p className="mt-1 font-medium text-amber-300">{socialCoverage?.teamsPartial ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Missing</p>
                  <p className="mt-1 font-medium text-red-300">{socialCoverage?.teamsMissing ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Verified Sources</p>
                  <p className="mt-1 font-medium text-white">{socialCoverage?.verifiedSources ?? 0}</p>
                </div>
              </div>

              <div className="mt-4 overflow-x-auto rounded-2xl border border-white/10">
                <table className="min-w-full divide-y divide-white/10 text-sm">
                  <thead className="bg-black/20 text-zinc-500">
                    <tr>
                      <th className="px-4 py-3 text-left font-medium">Team</th>
                      <th className="px-4 py-3 text-left font-medium">Sources Active</th>
                      <th className="px-4 py-3 text-left font-medium">Verified Sources</th>
                      <th className="px-4 py-3 text-left font-medium">Tier 1</th>
                      <th className="px-4 py-3 text-left font-medium">Tier 2</th>
                      <th className="px-4 py-3 text-left font-medium">Tier 3</th>
                      <th className="px-4 py-3 text-left font-medium">Coverage Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/10 bg-[#0D131C] text-zinc-300">
                    {(socialCoverage?.teams ?? []).map((team) => (
                      <tr key={team.team}>
                        <td className="px-4 py-3 font-medium text-white">{team.team}</td>
                        <td className="px-4 py-3">{team.sourcesActive}</td>
                        <td className="px-4 py-3">{team.verifiedSources}</td>
                        <td className="px-4 py-3">{team.tier1}</td>
                        <td className="px-4 py-3">{team.tier2}</td>
                        <td className="px-4 py-3">{team.tier3}</td>
                        <td className="px-4 py-3">
                          <span className={`rounded-full border px-2.5 py-1 text-xs ${
                            team.coverageStatus === "COMPLETE"
                              ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-400"
                              : team.coverageStatus === "PARTIAL"
                                ? "border-amber-400/20 bg-amber-400/10 text-amber-300"
                                : "border-red-400/20 bg-red-400/10 text-red-300"
                          }`}>
                            {team.coverageStatus}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="mt-6 rounded-3xl border border-white/10 bg-[#0B1119] p-6">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">Injury Status</h2>
                <span className={`rounded-full border px-3 py-1 text-xs ${
                  status.injuryDataStatus === "LIVE"
                    ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-400"
                    : status.injuryDataStatus === "CACHED"
                      ? "border-sky-400/20 bg-sky-400/10 text-sky-400"
                      : status.injuryDataStatus === "MOCK"
                        ? "border-amber-400/20 bg-amber-400/10 text-amber-400"
                        : "border-zinc-700 bg-zinc-800 text-zinc-400"
                }`}>
                  {status.injuryDataStatus ?? "MOCK"}
                </span>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Injury Provider</p>
                  <p className="mt-1 font-medium text-white">{status.injuryProvider ?? "ESPN (Public)"}</p>
                  <p className="text-[10px] text-zinc-600">{status.injuryIsLive ? "Live" : "No credentials required"}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Last Injury Refresh</p>
                  <p className="mt-1 font-medium text-white">
                    {status.lastInjuryRefresh ? new Date(status.lastInjuryRefresh).toLocaleString() : "n/a"}
                  </p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Players Tracked</p>
                  <p className="mt-1 font-medium text-white">{status.injuryPlayersTracked ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Teams Updated</p>
                  <p className="mt-1 font-medium text-white">{status.injuryTeamsUpdated ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm col-span-full">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Last Error</p>
                  <p className="mt-1 text-xs font-medium text-amber-400 break-words">
                    {status.lastInjuryError ?? "None"}
                  </p>
                </div>
              </div>
            </section>

            <section className="mt-6 rounded-3xl border border-white/10 bg-[#0B1119] p-6">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">Weather Status</h2>
                <span className={`rounded-full border px-3 py-1 text-xs ${
                  status.weatherDataStatus === "LIVE"
                    ? "border-emerald-400/20 bg-emerald-400/10 text-emerald-400"
                    : status.weatherDataStatus === "CACHED"
                      ? "border-sky-400/20 bg-sky-400/10 text-sky-400"
                      : status.weatherDataStatus === "MOCK"
                        ? "border-amber-400/20 bg-amber-400/10 text-amber-400"
                        : "border-zinc-700 bg-zinc-800 text-zinc-400"
                }`}>
                  {status.weatherDataStatus ?? "MOCK"}
                </span>
              </div>
              <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Weather Provider</p>
                  <p className="mt-1 font-medium text-white">{status.weatherProvider ?? "Open-Meteo (Free)"}</p>
                  <p className="text-[10px] text-zinc-600">No credentials required</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Last Weather Refresh</p>
                  <p className="mt-1 font-medium text-white">
                    {status.lastWeatherRefresh ? new Date(status.lastWeatherRefresh).toLocaleString() : "n/a"}
                  </p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Games Updated</p>
                  <p className="mt-1 font-medium text-white">{status.weatherGamesUpdated ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Forecasts Available</p>
                  <p className="mt-1 font-medium text-white">{status.weatherForecastsAvailable ?? 0}</p>
                </div>
                <div className="rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm col-span-full">
                  <p className="text-zinc-500 text-[10px] uppercase tracking-widest">Last Error</p>
                  <p className="mt-1 text-xs font-medium text-amber-400 break-words">
                    {status.lastWeatherError ?? "None"}
                  </p>
                </div>
              </div>
            </section>
          </>
        ) : null}
      </div>
    </main>
  );
}
