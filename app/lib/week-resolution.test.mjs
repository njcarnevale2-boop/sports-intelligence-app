import test from "node:test";
import assert from "node:assert/strict";

import {
  buildBriefingWeekScopedRequestPaths,
  buildOpportunitiesRequestPath,
  normalizeAvailableWeeks,
  resolveCanonicalWeekFromDecisionBoard,
  resolveWeekFromOpportunitiesEnvelope,
} from "./week-resolution.ts";

test("resolves canonical week from decision board payload", () => {
  assert.equal(resolveCanonicalWeekFromDecisionBoard({ week: 5 }), 5);
  assert.equal(resolveCanonicalWeekFromDecisionBoard({ week: null }), null);
  assert.equal(resolveCanonicalWeekFromDecisionBoard({}), null);
});

test("opportunities request path is week-scoped and never unscoped games", () => {
  const path = buildOpportunitiesRequestPath(7);
  assert.equal(path, "/api/opportunities?limit=100&week=7");
  assert.ok(!path.includes("/api/games"));
});

test("briefing request paths are week-scoped and never include unscoped games", () => {
  const [gamesPath, opportunitiesPath] = buildBriefingWeekScopedRequestPaths(9);
  assert.equal(gamesPath, "/api/games?week=9");
  assert.equal(opportunitiesPath, "/api/opportunities?limit=100&week=9");
  assert.ok(!gamesPath.endsWith("/api/games"));
  assert.ok(!opportunitiesPath.includes("/api/games"));
});

test("manual week selection can vary dynamically with no hard-coded week", () => {
  assert.equal(buildOpportunitiesRequestPath(4), "/api/opportunities?limit=100&week=4");
  assert.equal(buildOpportunitiesRequestPath(5), "/api/opportunities?limit=100&week=5");
  assert.equal(buildBriefingWeekScopedRequestPaths(12)[0], "/api/games?week=12");
});

test("opportunities envelope week normalization preserves selected week and options", () => {
  const resolvedWeek = resolveWeekFromOpportunitiesEnvelope(
    { week: 6, availableWeeks: [3, 4, 6, 6] },
    4,
  );
  assert.equal(resolvedWeek, 6);

  const available = normalizeAvailableWeeks([3, 4, 6, 6], resolvedWeek);
  assert.deepEqual(available, [3, 4, 6]);

  const fallbackWeek = resolveWeekFromOpportunitiesEnvelope({}, 8);
  assert.equal(fallbackWeek, 8);
  assert.deepEqual(normalizeAvailableWeeks(undefined, fallbackWeek), [8]);
});