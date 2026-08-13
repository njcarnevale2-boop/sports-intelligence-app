import test from 'node:test';
import assert from 'node:assert/strict';

import { buildCardSummary, buildPortfolioRiskWarnings, getBestLineAndPriceOffers, normalizeSavedBet } from './my-card-helpers.ts';

test('buildCardSummary aggregates card metrics', () => {
  const summary = buildCardSummary([
    normalizeSavedBet({
      id: '1',
      matchup: 'Bills @ Ravens',
      book: 'DraftKings',
      point: 3,
      price: -110,
      edge: 6.2,
      evPerDollar: 0.42,
      kelly20: 0.8,
      sportsIntelligenceScore: { score: 86 },
      marketIntelligence: { score: 78 },
      injuryContext: { summary: 'QB is limited', awayInjuryScore: 50, homeInjuryScore: 20 },
    }),
    normalizeSavedBet({
      id: '2',
      matchup: 'Chiefs @ Chargers',
      book: 'FanDuel',
      point: 7,
      price: 110,
      edge: 4.1,
      evPerDollar: 0.31,
      kelly20: 0.5,
      sportsIntelligenceScore: { score: 79 },
      marketIntelligence: { score: 81 },
      injuryContext: { summary: 'WR is healthy', awayInjuryScore: 10, homeInjuryScore: 5 },
    }),
  ]);

  assert.equal(summary.totalBets, 2);
  assert.equal(summary.averageSiScore, 82.5);
  assert.equal(summary.totalExpectedValue, 0.73);
  assert.equal(summary.recommendedBankrollExposure, 1.3);
  assert.equal(summary.averageEdge, 5.15);
});

test('buildPortfolioRiskWarnings flags correlated and overexposed bets', () => {
  const warnings = buildPortfolioRiskWarnings([
    normalizeSavedBet({
      id: '1',
      matchup: 'Bills @ Ravens',
      eventId: 'game-1',
      awayTeam: 'Bills',
      homeTeam: 'Ravens',
      recommendation: 'Play',
      kelly20: 0.9,
      sportsIntelligenceScore: { score: 85 },
    }),
    normalizeSavedBet({
      id: '2',
      matchup: 'Bills @ Patriots',
      eventId: 'game-2',
      awayTeam: 'Bills',
      homeTeam: 'Patriots',
      recommendation: 'Play',
      kelly20: 0.9,
      sportsIntelligenceScore: { score: 81 },
    }),
    normalizeSavedBet({
      id: '3',
      matchup: 'Jets @ Dolphins',
      eventId: 'game-3',
      awayTeam: 'Jets',
      homeTeam: 'Dolphins',
      recommendation: 'Play',
      kelly20: 0.9,
      sportsIntelligenceScore: { score: 77 },
    }),
  ]);

  assert.equal(warnings.length, 4);
  assert.match(warnings[0].message, /correlated/i);
});

test('getBestLineAndPriceOffers separates best line from best price', () => {
  const bet = normalizeSavedBet({
    matchup: 'Bills @ Ravens',
    book: 'Book A',
    market: 'spread',
    side: 'away',
    point: 2.5,
    price: -105,
    edge: 4.0,
    alternateBooks: [
      { book: 'Book B', point: 3.0, price: -120, edge: 4.2, evPerDollar: 0.2 },
      { book: 'Book C', point: 2.5, price: -101, edge: 3.8, evPerDollar: 0.19 },
    ],
  });

  const offers = getBestLineAndPriceOffers(bet);
  assert.equal(offers.bestLine?.book, 'Book B');
  assert.equal(offers.bestPrice?.book, 'Book C');
});

// ── Schema regression: full opportunity object written by addToCard ──────────

test('normalizeSavedBet preserves all display fields from a real opportunity', () => {
  const raw = {
    id: 'c1d3fcec25aaeb06ebd2244d33d338e0-spread-away',
    eventId: 'c1d3fcec25aaeb06ebd2244d33d338e0',
    matchup: 'NO @ DET',
    awayTeam: 'NO',
    homeTeam: 'DET',
    commenceTime: '2026-09-13 17:00:00',
    pick: 'NO +7',
    book: 'LowVig.ag',
    market: 'spread',
    side: 'away',
    point: 7.0,
    price: -105.0,
    confidence: 86,
    edge: 26.2,
    evPerDollar: 0.512,
    kelly20: 0.108,
    recommendation: 'STRONG BET',
    sportsIntelligenceScore: {
      score: 85,
      grade: 'A',
      stars: 5,
      recommendation: 'Strong Bet',
      components: { modelEdge: 90, expectedValue: 88, confidence: 86, marketIntelligence: 70, dataCompleteness: 75 },
      weights: { modelEdge: 0.3, expectedValue: 0.25, confidence: 0.2, marketIntelligence: 0.15, dataCompleteness: 0.1 },
      reasons: ['Strong model edge'],
    },
    injuryContext: { summary: 'Neutral', awayInjuryScore: 10, homeInjuryScore: 5 },
    alternateBooks: [{ book: 'DraftKings', point: 6.5, price: -110, edge: 25.0, evPerDollar: 0.48 }],
  };

  const bet = normalizeSavedBet(raw);

  assert.equal(bet.awayTeam, 'NO');
  assert.equal(bet.homeTeam, 'DET');
  assert.equal(bet.commenceTime, '2026-09-13 17:00:00');
  assert.equal(bet.point, 7.0);
  assert.equal(bet.price, -105.0);
  assert.equal(bet.confidence, 86);
  assert.equal(bet.evPerDollar, 0.512);
  assert.equal(bet.kelly20, 0.108);
  assert.equal(bet.sportsIntelligenceScore?.score, 85);
  assert.equal(bet.sportsIntelligenceScore?.recommendation, 'Strong Bet');
  assert.equal(bet.sportsIntelligenceScore?.grade, 'A');
  assert.equal(bet.injuryContext?.summary, 'Neutral');
  assert.equal(bet.alternateBooks?.length, 1);
});

test('normalizeSavedBet handles legacy bets (old static stub schema) safely', () => {
  const legacy = {
    matchup: 'Bills @ Ravens',
    pick: 'Buffalo +3',
    book: 'FanDuel',
    confidence: 91,
    edge: '+6.8%',
    // no eventId, awayTeam, homeTeam, commenceTime, point, price, sportsIntelligenceScore
  };

  const bet = normalizeSavedBet(legacy);

  assert.equal(bet.matchup, 'Bills @ Ravens');
  assert.equal(bet.pick, 'Buffalo +3');
  assert.equal(bet.book, 'FanDuel');
  assert.equal(bet.awayTeam, undefined);
  assert.equal(bet.homeTeam, undefined);
  assert.equal(bet.commenceTime, undefined);
  assert.equal(bet.point, undefined);
  assert.equal(bet.price, undefined);
  assert.equal(bet.sportsIntelligenceScore, undefined);
  // Confidence preserved
  assert.equal(bet.confidence, 91);
});

test('normalizeSavedBet handles missing optional fields without throwing', () => {
  const minimal = { matchup: 'Jets @ Bills', book: 'DraftKings', edge: 5.2 };
  const bet = normalizeSavedBet(minimal);

  assert.equal(bet.matchup, 'Jets @ Bills');
  assert.equal(bet.pick, 'Market edge');
  assert.equal(bet.book, 'DraftKings');
  assert.equal(bet.sportsIntelligenceScore, undefined);
  assert.equal(bet.kelly20, undefined);
});

test('normalizeSavedBet preserves sportsIntelligenceScore.recommendation over raw recommendation', () => {
  const raw = {
    matchup: 'KC @ LV',
    book: 'FanDuel',
    edge: 8,
    recommendation: 'STRONG BET',
    sportsIntelligenceScore: { score: 88, recommendation: 'Strong Bet', grade: 'A+' },
  };

  const bet = normalizeSavedBet(raw);
  assert.equal(bet.sportsIntelligenceScore?.recommendation, 'Strong Bet');
  // raw recommendation is also preserved as fallback
  assert.equal(bet.recommendation, 'STRONG BET');
});
