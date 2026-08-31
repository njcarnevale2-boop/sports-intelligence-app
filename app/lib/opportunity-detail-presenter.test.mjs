import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

import {
  buildDecisionBoxes,
  buildPrimaryDecisionSnapshot,
  buildPrimaryWhySia,
  getMarketConfirmationLabel,
  shouldShowMarketDisagreementExplanation,
} from "./opportunity-detail-presenter.ts";

const baseOpportunity = {
  pick: "NO +7",
  point: 7,
  price: -105,
  book: "LowVig.ag",
  modelProbability: 77.4,
  impliedProbability: 51.2,
  edge: 26.2,
  evPerDollar: 0.512,
  confidence: 86,
  dataCompleteness: 90,
  awayTeam: "NO",
  homeTeam: "DET",
  marketIntelligence: {
    score: 2.2,
    consensus: 48,
  },
  injuryContext: {
    severity: "neutral",
  },
  truePlayableTo: -2,
  truePlayableToStatus: "AVAILABLE",
};

test("primary decision snapshot preserves canonical values", () => {
  const snapshot = buildPrimaryDecisionSnapshot(
    baseOpportunity,
    { score: 82.8, recommendation: "STRONG BET" },
    "Strong",
    "Weak"
  );

  assert.equal(snapshot.betLinePrice, "NO +7 (-105)");
  assert.equal(snapshot.recommendation, "STRONG BET");
  assert.equal(snapshot.siScore, 82.8);
  assert.equal(snapshot.siaWinProbability, 77.4);
  assert.equal(snapshot.marketImpliedProbability, 51.2);
  assert.equal(snapshot.bestSportsbook, "LowVig.ag");
  assert.equal(snapshot.playableTo, "NO -2");
  assert.equal(snapshot.stakeRecommendation, "Strong");
});

test("plain-language explanation is deterministic and includes model, market, value, and confirmation", () => {
  const text = buildPrimaryWhySia(
    baseOpportunity,
    {
      awayTeam: "NO",
      homeTeam: "DET",
      model: {
        marginHome: -3.2,
        projectedScore: {
          away: 26.1,
          home: 22.9,
        },
      },
      market: {
        homeSpread: -7,
      },
    },
    "Weak"
  );

  assert.match(text, /SIA projects NO 26\.1-DET 22\.9/);
  assert.match(text, /market currently has DET favored by 7\.0/);
  assert.match(text, /creating a 26\.2-point model edge on NO \+7/);
  assert.match(text, /Sportsbooks have not yet strongly confirmed the model's view/);
});

test("weak market confirmation warning appears only for bet recommendations", () => {
  assert.equal(shouldShowMarketDisagreementExplanation("STRONG BET", 2.5), true);
  assert.equal(shouldShowMarketDisagreementExplanation("BET", 4.9), true);
  assert.equal(shouldShowMarketDisagreementExplanation("PASS", 2.5), false);
  assert.equal(shouldShowMarketDisagreementExplanation("NO BET", 1.5), false);
});

test("decision boxes do not fabricate risk when no risk signals are present", () => {
  const boxes = buildDecisionBoxes(
    {
      ...baseOpportunity,
      marketIntelligence: { score: 8.2, consensus: 82 },
      injuryContext: { severity: "neutral" },
      dataCompleteness: 92,
    },
    { dataStatus: "LIVE" }
  );

  assert.ok(boxes.whyBetIt.length > 0);
  assert.deepEqual(boxes.whatCouldGoWrong, ["No material risk signal is currently elevated"]);
  assert.ok(boxes.whatToWatch.some((line) => line.includes("Line movement before kickoff")));
});

test("opportunity detail page keeps advanced disclosure and removes repetitive headers", () => {
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);
  const pagePath = resolve(__dirname, "../opportunities/[id]/page.tsx");
  const text = readFileSync(pagePath, "utf8");

  assert.match(text, /Advanced Analysis/);
  assert.match(text, /Why SIA Likes It/);
  assert.match(text, /Full Kelly/);
  assert.match(text, /Model Probability/);
  assert.match(text, /Market Score/);
  assert.doesNotMatch(text, /AT_BOUNDARY/);
  assert.doesNotMatch(text, /Executive Recommendation/);
  assert.doesNotMatch(text, /Bottom Line/);
  assert.doesNotMatch(text, /Why SIA Likes This Bet/);
  assert.doesNotMatch(text, /Executive Summary/);
});

test("market confirmation label mapping is user-friendly", () => {
  assert.equal(getMarketConfirmationLabel(7.5), "Strong");
  assert.equal(getMarketConfirmationLabel(5.5), "Mixed");
  assert.equal(getMarketConfirmationLabel(3.2), "Weak");
});
