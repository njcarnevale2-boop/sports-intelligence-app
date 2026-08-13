"use client";

type DataStatus = "LIVE" | "CACHED" | "MOCK" | "UNAVAILABLE" | "FILE" | string;

function statusColor(status: DataStatus) {
  switch (status) {
    case "LIVE":   return "border-emerald-400/25 bg-emerald-400/10 text-emerald-300";
    case "CACHED": return "border-sky-400/25 bg-sky-400/10 text-sky-300";
    case "MOCK":   return "border-amber-400/25 bg-amber-400/10 text-amber-300";
    default:       return "border-zinc-700/50 bg-zinc-800/40 text-zinc-500";
  }
}

function normalizeStatus(status: DataStatus): string {
  // "FILE" is a backend-internal label — show it as "LIVE" since the data is current
  if (status === "FILE") return "LIVE";
  return status;
}

export default function FreshnessBadge({
  status,
  lastUpdated,
  label,
}: {
  status: DataStatus;
  lastUpdated?: string | null;
  label?: string;
}) {
  const display = normalizeStatus(status);

  let timeLabel = "";
  if (lastUpdated) {
    try {
      const date = new Date(lastUpdated);
      if (!Number.isNaN(date.getTime())) {
        const diffMs = Date.now() - date.getTime();
        const diffMin = Math.round(diffMs / 60000);
        if (diffMin < 2)        timeLabel = "just now";
        else if (diffMin < 60)  timeLabel = `${diffMin}m ago`;
        else if (diffMin < 1440) timeLabel = `${Math.round(diffMin / 60)}h ago`;
        else                    timeLabel = date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
      }
    } catch {
      // ignore invalid date
    }
  }

  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-medium uppercase tracking-widest ${statusColor(display as DataStatus)}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${display === "LIVE" ? "bg-emerald-400" : display === "CACHED" ? "bg-sky-400" : display === "MOCK" ? "bg-amber-400" : "bg-zinc-600"}`} />
      {label ? `${label} · ` : ""}{display}
      {timeLabel ? <span className="ml-0.5 opacity-70">· {timeLabel}</span> : null}
    </span>
  );
}
