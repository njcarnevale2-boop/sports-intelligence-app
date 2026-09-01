import test from "node:test";
import assert from "node:assert/strict";

import {
  buildLineStatusMessage,
  formatBetRange,
  formatModelCushion,
  formatProbabilityEdge,
  getModelCushionDistance,
  modelCushionSubtext,
  probabilityEdgeSubtext,
} from "./home-decision-clarity.ts";

const base = {
  selection: "NO +7",
  recommendedPlayableTo: 3,
  recommendedPlayableToStatus: "AVAILABLE",
  edge: 6.4,
  modelProbability: 0.574,
  marketImpliedProbability: 0.511,
  line: 7,
  price: -105,
  sportsbook: "BookA",
};

test("bet range stays anchored to the current executable line", () => {
  assert.equal(formatBetRange(base), "NO +7 or better");

  const unavailable = {
    ...base,
    line: null,
  };
  assert.equal(formatBetRange(unavailable), "Unavailable");
});

test("model cushion is deterministic and display-only", () => {
  assert.equal(getModelCushionDistance(base), 4);
  assert.equal(formatModelCushion(base), "STRONG");
  assert.match(modelCushionSubtext(base), /Display-only model cushion/);

  assert.equal(formatModelCushion({ ...base, line: 3 }), "MINIMAL");
  assert.equal(formatModelCushion({ ...base, line: 3.5 }), "LIMITED");
  assert.equal(formatModelCushion({ ...base, line: 5 }), "MODERATE");
  assert.equal(
    formatModelCushion({ ...base, recommendedPlayableToStatus: "UNAVAILABLE" }),
    "Unavailable",
  );
});

test("model cushion does not change with probability or EV fields", () => {
  const baseline = formatModelCushion(base);
  const changedMath = formatModelCushion({
    ...base,
    edge: -2.4,
    modelProbability: 0.51,
    marketImpliedProbability: 0.58,
  });

  assert.equal(baseline, "STRONG");
  assert.equal(changedMath, baseline);
});

test("probability edge formatting is bettor-friendly", () => {
  assert.equal(formatProbabilityEdge(6.4), "+6.4%");
  assert.equal(formatProbabilityEdge(-1.1), "-1.1%");
  assert.equal(probabilityEdgeSubtext(base), "SIA 57.4% vs market 51.1%");
});

test("line status message asks for current-line verification", () => {
  const now = new Date("2026-09-01T12:10:00Z");
  const message = buildLineStatusMessage(
    base,
    "FRESH",
    "2026-09-01T12:05:00Z",
    now,
  );

  assert.equal(message.heading, "LINE APPEARS CURRENT");
  assert.match(message.detail, /SIA last saw \+7 \(-105\) at BookA 5m ago\./);
  assert.match(message.detail, /Confirm the line and price are still available before betting\./);

  const staleMessage = buildLineStatusMessage(base, "STALE", null, now);
  assert.equal(staleMessage.heading, "CHECK CURRENT LINE");
  assert.match(staleMessage.detail, /outdated|confirm the current line and price/i);
});
