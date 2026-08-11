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
