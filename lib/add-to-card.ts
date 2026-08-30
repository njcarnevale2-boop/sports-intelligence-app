/**
 * addToCard — shared helper for all "Add to My Card" entry points.
 *
 * Writes to localStorage AND fires POST /api/recommendation/snapshot so
 * performance tracking begins immediately. Snapshot failures are surfaced to the
 * caller via the returned status object; they do NOT silently succeed.
 */

import { fetchJson } from "@/app/lib/api";

export type SavedCardItem = Record<string, unknown>;

const CARD_KEY = "sports-intelligence-card";
const PARTIAL_TRACKING_WARNING = "Added to My Card. Performance tracking could not be fully started.";

type SnapshotTrackingStatus = "COMPLETE" | "PARTIAL" | "FAILED";

type SnapshotResponse = {
  success: boolean;
  snapshotRecorded?: boolean;
  ledgerRecorded?: boolean;
  trackingStatus?: SnapshotTrackingStatus;
  snapshotId?: string;
  reason?: string;
  warning?: string;
};

export type AddToCardResult =
  | { success: true; alreadyExists: boolean; snapshotId?: string; trackingStatus: "COMPLETE" | "PARTIAL"; warning?: string }
  | { success: false; error: string; trackingStatus: "FAILED" };

export async function addToCard(item: SavedCardItem): Promise<AddToCardResult> {
  const id = item.id as string | undefined;

  // Read existing card
  let current: SavedCardItem[] = [];
  try {
    const raw = localStorage.getItem(CARD_KEY);
    if (raw) current = JSON.parse(raw) as SavedCardItem[];
  } catch {
    current = [];
  }

  // Duplicate check by eventId + market + side (more specific than id alone)
  const alreadyExists = current.some(
    (existing) =>
      existing.id === id ||
      (existing.eventId === item.eventId &&
        existing.market === item.market &&
        existing.side === item.side)
  );

  if (!alreadyExists) {
    current.push(item);
    localStorage.setItem(CARD_KEY, JSON.stringify(current));
  }

  // Always attempt snapshot, even if already in localStorage (idempotent on backend)
  try {
    const snap = await fetchJson<SnapshotResponse>(
      "/api/recommendation/snapshot",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          eventId:           item.eventId,
          id:                item.id,
          market:            item.market,
          side:              item.side,
          selection:         item.pick,
          point:             item.point,
          price:             item.price,
          sportsbook:        item.book,
          recommendation:    item.recommendation,
          qualificationStatus: item.qualificationStatus,
          qualificationReasons: item.qualificationReasons,
          siScore:           (item.sportsIntelligenceScore as { score?: number } | undefined)?.score,
          siGrade:           (item.sportsIntelligenceScore as { grade?: string } | undefined)?.grade,
          siRank:            item.rank,
          modelProbability:  item.modelProbability,
          rawModelProbability: item.rawModelProbability,
          calibratedProbability: item.calibratedProbability ?? item.currentWinProbability,
          pushProbability:   item.currentPushProbability,
          lossProbability:   item.currentLossProbability,
          edge:              item.edge,
          rawEdge:           item.rawEdge,
          calibratedEdge:    item.calibratedEdge,
          currentEV:         item.currentEV,
          evPerDollar:       item.evPerDollar,
          fairLine:          item.fairLine,
          truePlayableTo:    item.truePlayableTo,
          truePlayableToStatus: item.truePlayableToStatus,
          oddsProvider:      item.marketProvider,
          marketTimestamp:   item.marketLastUpdated,
          calibrationVersion: item.calibrationVersion,
          rankingVersion:    item.rankingVersion,
          qualificationPolicyVersion: item.qualificationPolicyVersion,
          commenceTime:      item.commenceTime,
          homeTeam:          item.homeTeam,
          awayTeam:          item.awayTeam,
          marketIntelligence: item.marketIntelligence,
          injuryContext:     item.injuryContext,
          weatherContext:    item.weatherContext,
        }),
      }
    );

    if (snap.trackingStatus === "PARTIAL" && snap.snapshotRecorded) {
      return {
        success: true,
        alreadyExists,
        snapshotId: snap.snapshotId,
        trackingStatus: "PARTIAL",
        warning: snap.warning || PARTIAL_TRACKING_WARNING,
      };
    }

    if (!snap.success || snap.trackingStatus === "FAILED") {
      return {
        success: false,
        trackingStatus: "FAILED",
        error: snap.reason ?? "Performance tracking could not be started right now.",
      };
    }

    return {
      success: true,
      alreadyExists,
      snapshotId: snap.snapshotId,
      trackingStatus: "COMPLETE",
    };
  } catch (err) {
    // Backend unavailable — card is still saved locally, but tracking could not be started.
    return {
      success: false,
      trackingStatus: "FAILED",
      error: "Added to My Card. Performance tracking could not be started right now.",
    };
  }
}

export function removeFromCard(idOrEventId: string): void {
  let current: SavedCardItem[] = [];
  try {
    const raw = localStorage.getItem(CARD_KEY);
    if (raw) current = JSON.parse(raw) as SavedCardItem[];
  } catch {
    current = [];
  }
  const filtered = current.filter(
    (item) => item.id !== idOrEventId && item.eventId !== idOrEventId
  );
  localStorage.setItem(CARD_KEY, JSON.stringify(filtered));
}

export function readCard(): SavedCardItem[] {
  try {
    const raw = localStorage.getItem(CARD_KEY);
    return raw ? (JSON.parse(raw) as SavedCardItem[]) : [];
  } catch {
    return [];
  }
}
