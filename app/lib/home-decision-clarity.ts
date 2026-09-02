type HomeDecisionItem = {
  selection: string;
  line: number | null;
  recommendedPlayableTo: number | null;
  recommendedPlayableToStatus?: string | null;
  edge: number | null;
  modelProbability: number | null;
  marketImpliedProbability: number | null;
  price: number | null;
  sportsbook: string | null;
  recommendationStatus?: string | null;
  qualificationStatus?: string | null;
  rank?: number | null;
};

function formatSigned(value: number | null | undefined) {
  if (value == null) return "Unavailable";
  return value > 0 ? `+${value}` : `${value}`;
}

function teamFromSelection(selection: string) {
  const team = String(selection || "").trim().split(" ")[0];
  return team || "Selection";
}

export function formatBetRange(item: HomeDecisionItem) {
  if (item.line == null || !Number.isFinite(item.line)) {
    return "Unavailable";
  }
  return `${teamFromSelection(item.selection)} ${formatSigned(item.line)} or better`;
}

export function getModelCushionDistance(item: HomeDecisionItem) {
  if (item.recommendedPlayableToStatus !== "AVAILABLE") return null;
  if (item.line == null || item.recommendedPlayableTo == null) return null;
  if (!Number.isFinite(item.line) || !Number.isFinite(item.recommendedPlayableTo)) return null;
  return Math.abs(item.line - item.recommendedPlayableTo);
}

export function formatModelCushion(item: HomeDecisionItem) {
  const distance = getModelCushionDistance(item);
  if (distance == null) return "Unavailable";

  if (distance === 0) return "MINIMAL";
  if (distance <= 1.0) return "LIMITED";
  if (distance <= 2.5) return "MODERATE";
  return "STRONG";
}

export function modelCushionSubtext(item: HomeDecisionItem) {
  const cushion = formatModelCushion(item);
  if (cushion === "STRONG") return "SIA sees substantial model value beyond the current line.";
  if (cushion === "MODERATE") return "SIA sees meaningful model value beyond the current line.";
  if (cushion === "LIMITED") return "SIA sees some model value beyond the current line.";
  if (cushion === "MINIMAL") return "SIA's edge is concentrated near the current line.";
  return "Model cushion is unavailable for this matchup.";
}

export function modelAdvantageLabel(item: HomeDecisionItem) {
  const recommendation = String(item.recommendationStatus || "").toUpperCase();
  const qualified = String(item.qualificationStatus || "").toUpperCase() === "QUALIFIED";
  if (!qualified) return "SMALL";
  if (recommendation.includes("STRONG")) return "STRONG";
  if (recommendation.includes("BET")) return "MODERATE";
  if ((item.rank ?? 9999) <= 1) return "MODERATE";
  return "SMALL";
}

export function modelAdvantageSubtext(item: HomeDecisionItem) {
  const label = modelAdvantageLabel(item);
  if (label === "STRONG") {
    return "SIA rates this as one of the strongest current opportunities on its board.";
  }
  if (label === "MODERATE") {
    return "SIA rates this as a qualified opportunity with moderate relative strength.";
  }
  return "SIA sees only a small current advantage at this quote.";
}

export function conciseWhySiaLikesIt(item: HomeDecisionItem) {
  const recommendation = String(item.recommendationStatus || "").toUpperCase();
  if (recommendation.includes("STRONG")) {
    return "SIA ranks this as a strong qualified spread opportunity at the currently observed quote.";
  }
  if (recommendation.includes("BET")) {
    return "SIA ranks this as a qualified spread opportunity at the currently observed quote.";
  }
  if (recommendation.includes("LEAN")) {
    return "SIA sees a lean, but the current quote is not yet a full-conviction bet.";
  }
  return "SIA is waiting for a stronger setup before elevating this opportunity.";
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
      heading: freshness === "FRESH" ? "LINE LOOKS CURRENT" : "CHECK BEFORE BETTING",
      detail: `SIA last saw ${quote} ${age}. Confirm the line and price are still available before betting.`,
    };
  }

  if (freshness === "STALE" || freshness === "UNKNOWN") {
    return {
      heading: "CHECK BEFORE BETTING",
      detail: "This quote may be outdated. Confirm the current line and price before betting.",
    };
  }

  return {
    heading: "CHECK BEFORE BETTING",
    detail: `SIA last saw ${quote}. Confirm the line and price are still available before betting.`,
  };
}
