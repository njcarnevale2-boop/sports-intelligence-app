"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";

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
  errorLog: Array<{ timestamp: string; message: string }>;
};

const metricCard = (label: string, value: string | number, accent = "text-white") => (
  <div className="rounded-2xl border border-white/10 bg-[#0B1119] p-5">
    <p className="text-[10px] uppercase tracking-[0.18em] text-zinc-600">{label}</p>
    <p className={`mt-2 text-2xl font-semibold ${accent}`}>{value}</p>
  </div>
);

export default function AdminPage() {
  const [status, setStatus] = useState<AdminStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadStatus = async () => {
    try {
      setLoading(true);
      const response = await fetch("http://localhost:8000/api/admin/status");
      if (!response.ok) throw new Error("Status unavailable");
      const payload = await response.json();
      setStatus(payload);
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
      const response = await fetch("http://localhost:8000/api/admin/refresh", { method: "POST" });
      if (!response.ok) throw new Error("Refresh failed");
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
          </>
        ) : null}
      </div>
    </main>
  );
}
