type WeekLike = {
  week?: number | null;
};

export type OpportunitiesWeekEnvelope = {
  week?: number;
  availableWeeks?: number[];
  defaultWeek?: number | null;
  canonicalWeek?: { week?: number | null };
};

function toPositiveWeek(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }

  const asInt = Math.trunc(value);
  return asInt > 0 ? asInt : null;
}

export function resolveCanonicalWeekFromDecisionBoard(source: WeekLike | null | undefined): number | null {
  return toPositiveWeek(source?.week);
}

export function resolveWeekFromOpportunitiesEnvelope(
  envelope: OpportunitiesWeekEnvelope | null | undefined,
  requestedWeek: number,
): number {
  return (
    toPositiveWeek(envelope?.week) ??
    toPositiveWeek(envelope?.defaultWeek) ??
    toPositiveWeek(envelope?.canonicalWeek?.week) ??
    requestedWeek
  );
}

export function normalizeAvailableWeeks(weeks: number[] | undefined, selectedWeek: number): number[] {
  const deduped = new Set<number>();

  for (const candidate of weeks ?? []) {
    const normalized = toPositiveWeek(candidate);
    if (normalized != null) {
      deduped.add(normalized);
    }
  }

  deduped.add(selectedWeek);
  return Array.from(deduped).sort((a, b) => a - b);
}

export function buildOpportunitiesRequestPath(week: number): string {
  const query = new URLSearchParams({ limit: "100", week: String(week) });
  return `/api/opportunities?${query.toString()}`;
}

export function buildBriefingWeekScopedRequestPaths(week: number): [string, string] {
  return [
    `/api/games?week=${week}`,
    buildOpportunitiesRequestPath(week),
  ];
}