import test from "node:test";
import assert from "node:assert/strict";

import {
  buildLineStatusMessage,
  conciseWhySiaLikesIt,
  formatBetRange,
  formatModelCushion,
  getModelCushionDistance,
  modelAdvantageLabel,
  modelAdvantageSubtext,
  modelCushionSubtext,
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
  recommendationStatus: "STRONG BET",
  qualificationStatus: "QUALIFIED",
  rank: 1,
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
  assert.equal(modelCushionSubtext(base), "SIA sees substantial model value beyond the current line.");

  assert.equal(formatModelCushion({ ...base, line: 3 }), "MINIMAL");
  assert.equal(formatModelCushion({ ...base, line: 3.5 }), "LIMITED");
  assert.equal(formatModelCushion({ ...base, line: 5 }), "MODERATE");
  assert.equal(
    formatModelCushion({ ...base, recommendedPlayableToStatus: "UNAVAILABLE" }),
    "Unavailable",
  );
});

test("model cushion copy is bettor-friendly and hides theoretical boundary numbers", () => {
  assert.equal(modelCushionSubtext({ ...base, line: 3 }), "SIA's edge is concentrated near the current line.");
  assert.equal(modelCushionSubtext({ ...base, line: 3.5 }), "SIA sees some model value beyond the current line.");
  assert.equal(modelCushionSubtext({ ...base, line: 5 }), "SIA sees meaningful model value beyond the current line.");
  assert.equal(modelCushionSubtext(base), "SIA sees substantial model value beyond the current line.");
  assert.doesNotMatch(modelCushionSubtext(base), /theoretical|boundary|pts|\d/i);
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

test("model advantage is qualitative and deterministic", () => {
  assert.equal(modelAdvantageLabel(base), "STRONG");
  assert.equal(modelAdvantageSubtext(base), "SIA rates this as one of the strongest current opportunities on its board.");

  const moderate = { ...base, recommendationStatus: "BET" };
  assert.equal(modelAdvantageLabel(moderate), "MODERATE");

  const small = { ...base, recommendationStatus: "WATCH", qualificationStatus: "NOT_QUALIFIED" };
  assert.equal(modelAdvantageLabel(small), "SMALL");
  assert.equal(modelAdvantageSubtext(small), "SIA sees only a small current advantage at this quote.");
});

test("concise why copy avoids raw probability and edge precision", () => {
  const why = conciseWhySiaLikesIt(base);
  assert.match(why, /strong qualified spread opportunity/i);
  assert.doesNotMatch(why, /%|probability|edge|ev|\$1|\d+\.\d+/i);
});

test("line status message asks for current-line verification", () => {
  const now = new Date("2026-09-01T12:10:00Z");
  const message = buildLineStatusMessage(
    base,
    "FRESH",
    "2026-09-01T12:05:00Z",
    now,
  );

  assert.equal(message.heading, "LINE LOOKS CURRENT");
  assert.match(message.detail, /SIA last saw \+7 \(-105\) at BookA 5m ago\./);
  assert.match(message.detail, /Confirm the line and price are still available before betting\./);

  const staleMessage = buildLineStatusMessage(base, "STALE", null, now);
  assert.equal(staleMessage.heading, "CHECK BEFORE BETTING");
  assert.match(staleMessage.detail, /outdated|confirm the current line and price/i);
});
