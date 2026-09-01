type HomeDecisionItem = {
  selection: string;
  recommendedPlayableTo: number | null;
  recommendedPlayableToStatus?: string | null;
  edge: number | null;
  modelProbability: number | null;
  marketImpliedProbability: number | null;
  line: number | null;
  price: number | null;
  sportsbook: string | null;
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

function teamFromSelection(selection: string) {
  const team = String(selection || "").trim().split(" ")[0];
  return team || "Selection";
}

export function formatRecommendedTo(item: HomeDecisionItem) {
  if (item.recommendedPlayableToStatus !== "AVAILABLE" || item.recommendedPlayableTo == null) {
    return "Unavailable";
  }
  return `${teamFromSelection(item.selection)} ${formatSigned(item.recommendedPlayableTo)}`;
}

export function formatProbabilityEdge(edge: number | null) {
  if (edge == null) return "Unavailable";
  const sign = edge >= 0 ? "+" : "";
  return `${sign}${edge.toFixed(1)}%`;
}

export function probabilityEdgeSubtext(item: HomeDecisionItem) {
  return `SIA ${formatPercent(item.modelProbability)} vs market ${formatPercent(item.marketImpliedProbability)}`;
}

export function formatExecutableQuote(line: number | null, price: number | null, sportsbook: string | null) {
  const lineText = line != null ? formatSigned(line) : null;
  const priceText = price != null ? formatSigned(price) : null;
  const book = sportsbook || "Unavailable";
  if (lineText && priceText) return `${lineText} (${priceText}) at ${book}`;
  if (priceText) return `${priceText} at ${book}`;
  if (lineText) return `${lineText} at ${book}`;
  return `Unavailable at ${book}`;
}

function ageText(lastUpdated: string, nowUtc: Date) {
  const then = Date.parse(lastUpdated);
  if (!Number.isFinite(then)) return null;
  const seconds = Math.max(0, Math.floor((nowUtc.getTime() - then) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function buildLineStatusMessage(
  item: HomeDecisionItem,
  quoteFreshness: string,
  quoteLastUpdated?: string | null,
  nowUtc: Date = new Date(),
) {
  const freshness = String(quoteFreshness || "").toUpperCase();
  const quote = formatExecutableQuote(item.line, item.price, item.sportsbook);
  const age = quoteLastUpdated ? ageText(quoteLastUpdated, nowUtc) : null;

  if (age) {
    return {
      heading: freshness === "FRESH" ? "LINE APPEARS CURRENT" : "CHECK CURRENT LINE",
      detail: `SIA last saw ${quote} ${age}. Confirm the line and price are still available before betting.`,
    };
  }

  if (freshness === "STALE" || freshness === "UNKNOWN") {
    return {
      heading: "CHECK CURRENT LINE",
      detail: "This quote may be outdated. Confirm the current line and price before betting.",
    };
  }

  return {
    heading: "CHECK CURRENT LINE",
    detail: `SIA last saw ${quote}. Confirm the line and price are still available before betting.`,
  };
}
