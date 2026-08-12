/**
 * addToCard — shared helper for all "Add to My Card" entry points.
 *
 * Writes to localStorage AND fires POST /api/recommendation/snapshot so
 * CLV tracking begins immediately.  Snapshot failures are surfaced to the
 * caller via the returned status object; they do NOT silently succeed.
 */

import { fetchJson } from "@/app/lib/api";

export type SavedCardItem = Record<string, unknown>;

const CARD_KEY = "sports-intelligence-card";

export type AddToCardResult =
  | { success: true; alreadyExists: boolean; snapshotId?: string }
  | { success: false; error: string };

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
    const snap = await fetchJson<{ success: boolean; snapshotId?: string; reason?: string }>(
      "/api/recommendation/snapshot",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          eventId:           item.eventId,
          market:            item.market,
          side:              item.side,
          point:             item.point,
          price:             item.price,
          sportsbook:        item.book,
          siScore:           (item.sportsIntelligenceScore as { score?: number } | undefined)?.score,
          modelProbability:  item.modelProbability,
          edge:              item.edge,
          evPerDollar:       item.evPerDollar,
          commenceTime:      item.commenceTime,
          homeTeam:          item.homeTeam,
          awayTeam:          item.awayTeam,
          marketIntelligence: item.marketIntelligence,
          injuryContext:     item.injuryContext,
          weatherContext:    item.weatherContext,
        }),
      }
    );
    if (!snap.success) {
      return { success: false, error: snap.reason ?? "Snapshot creation failed" };
    }
    return { success: true, alreadyExists, snapshotId: snap.snapshotId };
  } catch (err) {
    // Backend unavailable — card is still saved locally, but CLV tracking failed
    const msg = err instanceof Error ? err.message : "Unknown error";
    return { success: false, error: `Card saved locally but CLV tracking failed: ${msg}` };
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
