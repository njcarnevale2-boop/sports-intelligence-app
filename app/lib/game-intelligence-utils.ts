export type MarketIntelligenceSummary = {
  headline: string;
  detail: string;
};

export type DecisionStage = {
  label: string;
  spread: number;
  recommendation: string;
  qualificationStatus: string;
  status: string;
  boundaryStatus: string;
};

export function resolveAnalysisSnapshotId(responseSnapshotId?: string | null, urlSnapshotId?: string | null) {
  const canonical = (responseSnapshotId || "").trim();
  if (canonical) return canonical;
  const fromUrl = (urlSnapshotId || "").trim();
  return fromUrl || undefined;
}

export function buildAskSiaPayload(
  eventId: string,
  question: string,
  snapshotId?: string,
  moveTheLine?: Record<string, unknown>
) {
  return {
    eventId,
    question,
    snapshotId,
    moveTheLine,
  };
}

export function buildMoveTheLinePayload(
  eventId: string,
  hypotheticalSpread: number,
  assumedOdds: number,
  snapshotId?: string,
) {
  return {
    eventId,
    hypotheticalSpread,
    assumedOdds,
    snapshotId,
  };
}

export function moveTheLineErrorMessage(error: unknown) {
  const fallback = "Unable to evaluate this line right now.";
  if (!(error instanceof Error)) return fallback;
  const message = error.message.trim();
  if (!message) return fallback;

  const lower = message.toLowerCase();
  if (lower.includes("failed to fetch") || lower.includes("networkerror") || lower.includes("load failed")) {
    return fallback;
  }
  if (lower.includes("request timed out") || lower.includes("timeout")) {
    return "Line evaluation timed out. Please try again.";
  }

  return message;
}

export function interpretMarketIntelligence(state: {
  signal?: string;
  booksMoving?: number;
  booksTracked?: number;
  supportingBooks?: number;
  opposingBooks?: number;
  steamBooks?: number;
}) : MarketIntelligenceSummary {
  const signal = String(state.signal || "").toLowerCase();
  const moving = Number.isFinite(state.booksMoving) ? Number(state.booksMoving) : 0;
  const tracked = Number.isFinite(state.booksTracked) ? Number(state.booksTracked) : 0;
  const supporting = Number.isFinite(state.supportingBooks) ? Number(state.supportingBooks) : 0;
  const opposing = Number.isFinite(state.opposingBooks) ? Number(state.opposingBooks) : 0;
  const steam = Number.isFinite(state.steamBooks) ? Number(state.steamBooks) : 0;

  if (!tracked) {
    return {
      headline: "Market confirmation is unavailable.",
      detail: "SIA does not currently have enough market movement data for this selection.",
    };
  }

  if (signal.includes("resistance") || opposing > supporting) {
    return {
      headline: "Market has not confirmed SIA's view.",
      detail: `Only ${moving} of ${tracked} books are moving, and opposition outweighs support right now.`,
    };
  }

  if (signal.includes("confirmed") || supporting >= Math.max(2, opposing + 1)) {
    return {
      headline: "Market is reinforcing SIA's direction.",
      detail: `${moving} of ${tracked} books are moving with ${supporting} supporting signals${steam > 0 ? `, including ${steam} steam alerts` : ""}.`,
    };
  }

  return {
    headline: "Market confirmation is still developing.",
    detail: `${moving} of ${tracked} books are moving, but agreement is not broad yet.`,
  };
}

export function formatSpreadWithSign(value: number) {
  if (Math.abs(value) < 0.0001) return "PK";
  return value > 0 ? `+${value}` : `${value}`;
}

export function decisionBoundaryLabel(selection: string, boundary: number | null | undefined) {
  if (boundary == null || !Number.isFinite(boundary)) return "Unavailable";
  const team = (selection || "Selection").split(" ")[0] || "Selection";
  return `${team} ${formatSpreadWithSign(boundary)}`;
}

export function normalizeDecisionStages(stages: DecisionStage[] | null | undefined) {
  const rows = Array.isArray(stages) ? stages : [];
  return rows
    .filter((row) => Number.isFinite(row?.spread))
    .map((row) => ({
      ...row,
      spread: Number(row.spread),
    }));
}
