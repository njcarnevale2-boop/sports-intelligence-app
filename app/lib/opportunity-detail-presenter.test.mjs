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
  recommendedPlayableTo: 3,
  recommendedPlayableToStatus: "AVAILABLE",
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
  assert.equal(snapshot.recommendedTo, "NO +3");
  assert.equal(snapshot.mathematicalBoundary, "NO -2");
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
      spreadAnalysis: {
        edgePoints: 10.18,
      },
    },
    "Weak"
  );

  assert.match(text, /SIA projects NO 26\.1-DET 22\.9/);
  assert.match(text, /market currently has DET favored by 7\.0/);
  assert.match(text, /That is a 10\.2-point disagreement versus the current spread/);
  assert.match(text, /creating a 26\.2-point model edge on NO \+7/);
  assert.match(text, /Sportsbooks have not yet strongly confirmed the model's view/);
});

test("disagreement sentence uses canonical spreadAnalysis.edgePoints not presenter arithmetic", () => {
  const text = buildPrimaryWhySia(
    {
      ...baseOpportunity,
      pick: "DOG +4.5",
      edge: 11.4,
    },
    {
      awayTeam: "DOG",
      homeTeam: "FAV",
      model: {
        // Intentionally mismatch these values to prove they are not used for disagreement magnitude.
        marginHome: -0.5,
        projectedScore: {
          away: 23.0,
          home: 22.5,
        },
      },
      market: {
        homeSpread: -7.0,
      },
      spreadAnalysis: {
        edgePoints: 9.75,
      },
    },
    "Mixed"
  );

  assert.match(text, /That is a 9\.8-point disagreement versus the current spread/);
  assert.doesNotMatch(text, /6\.5-point disagreement/);
});

test("market orientation copy handles away underdog", () => {
  const text = buildPrimaryWhySia(
    { ...baseOpportunity, pick: "AWY +7" },
    {
      awayTeam: "AWY",
      homeTeam: "HME",
      model: { marginHome: -2.0, projectedScore: { away: 24.0, home: 22.0 } },
      market: { homeSpread: -7.0 },
      spreadAnalysis: { edgePoints: 5.0 },
    },
    "Weak"
  );

  assert.match(text, /HME favored by 7\.0/);
});

test("market orientation copy handles home underdog", () => {
  const text = buildPrimaryWhySia(
    { ...baseOpportunity, pick: "HME +3" },
    {
      awayTeam: "AWY",
      homeTeam: "HME",
      model: { marginHome: 1.0, projectedScore: { away: 20.0, home: 21.0 } },
      market: { homeSpread: 3.0 },
      spreadAnalysis: { edgePoints: 4.0 },
    },
    "Mixed"
  );

  assert.match(text, /AWY favored by 3\.0/);
});

test("market orientation copy handles away favorite", () => {
  const text = buildPrimaryWhySia(
    { ...baseOpportunity, pick: "AWY -2.5" },
    {
      awayTeam: "AWY",
      homeTeam: "HME",
      model: { marginHome: 0.2, projectedScore: { away: 21.5, home: 21.3 } },
      market: { homeSpread: 2.5 },
      spreadAnalysis: { edgePoints: 2.7 },
    },
    "Strong"
  );

  assert.match(text, /AWY favored by 2\.5/);
});

test("market orientation copy handles home favorite", () => {
  const text = buildPrimaryWhySia(
    { ...baseOpportunity, pick: "HME -4" },
    {
      awayTeam: "AWY",
      homeTeam: "HME",
      model: { marginHome: -4.5, projectedScore: { away: 17.0, home: 21.5 } },
      market: { homeSpread: -4.0 },
      spreadAnalysis: { edgePoints: 0.5 },
    },
    "Strong"
  );

  assert.match(text, /HME favored by 4\.0/);
});

test("market orientation copy handles near-zero spread as pick'em", () => {
  const text = buildPrimaryWhySia(
    { ...baseOpportunity, pick: "HME PK" },
    {
      awayTeam: "AWY",
      homeTeam: "HME",
      model: { marginHome: 0.0, projectedScore: { away: 20.0, home: 20.0 } },
      market: { homeSpread: 0.00001 },
      spreadAnalysis: { edgePoints: 0.0 },
    },
    "Mixed"
  );

  assert.match(text, /a pick'em/);
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

test("primary decision emphasizes recommended boundary and preserves mathematical boundary", () => {
  const withStatusMissing = buildPrimaryDecisionSnapshot(
    {
      ...baseOpportunity,
      recommendedPlayableTo: 5.5,
      recommendedPlayableToStatus: undefined,
      truePlayableTo: 5.5,
      truePlayableToStatus: undefined,
    },
    { score: 80.0, recommendation: "BET" },
    "Moderate",
    "Mixed"
  );

  assert.equal(withStatusMissing.recommendedTo, "NO +5.5");
  assert.equal(withStatusMissing.mathematicalBoundary, "NO +5.5");

  const withoutValue = buildPrimaryDecisionSnapshot(
    {
      ...baseOpportunity,
      recommendedPlayableTo: null,
      recommendedPlayableToStatus: "UNAVAILABLE",
      truePlayableTo: null,
      truePlayableToStatus: "UNAVAILABLE",
    },
    { score: 80.0, recommendation: "BET" },
    "Moderate",
    "Mixed"
  );

  assert.equal(withoutValue.recommendedTo, "See Game Intelligence");
  assert.equal(withoutValue.mathematicalBoundary, "Unavailable");
});
