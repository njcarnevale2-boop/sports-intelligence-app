import test from "node:test";
import assert from "node:assert/strict";

import {
  buildAskSiaPayload,
  buildMoveTheLinePayload,
  decisionBoundaryLabel,
  interpretMarketIntelligence,
  moveTheLineErrorMessage,
  normalizeDecisionStages,
  resolveAnalysisSnapshotId,
} from "./game-intelligence-utils.ts";

test("snapshot resolution prefers canonical response snapshot", () => {
  assert.equal(resolveAnalysisSnapshotId("snap-canonical", "snap-url"), "snap-canonical");
  assert.equal(resolveAnalysisSnapshotId("", "snap-url"), "snap-url");
  assert.equal(resolveAnalysisSnapshotId(undefined, undefined), undefined);
});

test("request payload builders preserve event, snapshot, and line context", () => {
  const askPayload = buildAskSiaPayload("evt-1", "Why this bet?", "snap-123", { hypothetical: {} });
  assert.equal(askPayload.eventId, "evt-1");
  assert.equal(askPayload.snapshotId, "snap-123");

  const movePayload = buildMoveTheLinePayload("evt-1", -2, -105, "snap-123");
  assert.deepEqual(movePayload, {
    eventId: "evt-1",
    hypotheticalSpread: -2,
    assumedOdds: -105,
    snapshotId: "snap-123",
  });
});

test("move-the-line error message hides raw failed fetch text", () => {
  assert.equal(moveTheLineErrorMessage(new Error("Failed to fetch")), "Unable to evaluate this line right now.");
  assert.equal(moveTheLineErrorMessage(new Error("Request timed out")), "Line evaluation timed out. Please try again.");
  assert.equal(moveTheLineErrorMessage(new Error("Model spread context is unavailable for this game.")), "Model spread context is unavailable for this game.");
});

test("market interpretation prioritizes bettor-friendly language", () => {
  const resistance = interpretMarketIntelligence({
    signal: "Market Resistance",
    booksMoving: 2,
    booksTracked: 10,
    supportingBooks: 0,
    opposingBooks: 1,
    steamBooks: 0,
  });
  assert.match(resistance.headline, /not confirmed/i);

  const confirmed = interpretMarketIntelligence({
    signal: "Confirmed",
    booksMoving: 5,
    booksTracked: 8,
    supportingBooks: 3,
    opposingBooks: 0,
    steamBooks: 1,
  });
  assert.match(confirmed.headline, /reinforcing/i);
});

test("decision boundary labels are team-oriented and crossing-zero safe", () => {
  assert.equal(decisionBoundaryLabel("NO +7", 3), "NO +3");
  assert.equal(decisionBoundaryLabel("NO +7", 0), "NO PK");
  assert.equal(decisionBoundaryLabel("NO +7", -2), "NO -2");
});

test("decision stages normalize numeric spread values", () => {
  const stages = normalizeDecisionStages([
    { label: "Current line", spread: 7, recommendation: "STRONG BET", qualificationStatus: "QUALIFIED", status: "PLAYABLE", boundaryStatus: "INSIDE" },
    { label: "Official bet through", spread: 3, recommendation: "BET", qualificationStatus: "QUALIFIED", status: "PLAYABLE", boundaryStatus: "INSIDE" },
  ]);

  assert.equal(stages.length, 2);
  assert.equal(stages[1].spread, 3);
});
