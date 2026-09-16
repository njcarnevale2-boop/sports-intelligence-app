import test from 'node:test';
import assert from 'node:assert/strict';

import { addToCard, readCard } from './add-to-card.ts';

function withWindow() {
  const storage = new Map();
  globalThis.localStorage = {
    getItem: (key) => (storage.has(key) ? storage.get(key) : null),
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: (key) => storage.delete(key),
  };
  globalThis.window = {
    localStorage: globalThis.localStorage,
    location: { pathname: '/' },
    setTimeout,
    clearTimeout,
  };
  return storage;
}

function restoreGlobals(originalWindow, originalLocalStorage, originalFetch) {
  globalThis.window = originalWindow;
  globalThis.localStorage = originalLocalStorage;
  globalThis.fetch = originalFetch;
}

test('addToCard persists current recommended units instead of defaulting to 1U', async () => {
  const originalWindow = globalThis.window;
  const originalLocalStorage = globalThis.localStorage;
  const originalFetch = globalThis.fetch;

  const storage = withWindow();
  let capturedBody = null;
  globalThis.fetch = async (_input, init) => {
    capturedBody = JSON.parse(String(init?.body ?? '{}'));
    return new Response(JSON.stringify({ success: true, trackingStatus: 'COMPLETE', snapshotId: 'snap-1' }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const result = await addToCard({
      id: 'opp-1',
      season: 2026,
      week: 1,
      eventId: 'evt-1',
      market: 'spread',
      side: 'away',
      pick: 'NO +4',
      point: 4,
      price: -105,
      book: 'FanDuel',
      modelTimestamp: '2026-09-13T14:58:00+00:00',
      modelVersion: 'sia_model_v2026_preseason',
      probabilityEngineVersion: 'empirical_residual_engine_v2026_preseason',
      calibrationVersion: 'guarded_isotonic_v2026_preseason',
      rankingVersion: 'ranking_calibrated_edge_v2026',
      qualificationPolicyVersion: 'qualification_explicit_policy_v2026',
      qualificationStatus: 'QUALIFIED',
      currentExecution: {
        status: 'AVAILABLE',
        sportsbook: 'FanDuel',
        point: 4,
        price: -105,
        quoteTimestamp: '2026-09-13T15:00:00+00:00',
        currentMarketTimestamp: '2026-09-13T15:01:00+00:00',
      },
      currentQualification: { status: 'QUALIFIED', actionable: true },
      currentSizing: {
        status: 'AVAILABLE',
        fullKellyFraction: 0.024,
        fractionalKellyFraction: 0.0048,
        bankrollPercent: 0.48,
        bankrollBasis: 1000,
        recommendedUnits: 0.48,
        recommendedAmount: 48,
        unitSize: 100,
      },
    });

    assert.equal(result.success, true);
    assert.equal(capturedBody.season, 2026);
    assert.equal(capturedBody.week, 1);
    assert.equal(capturedBody.unitsRisked, 0.48);
    assert.equal(capturedBody.amountRisked, 48);
    assert.equal(capturedBody.unitSizeAtBet, 100);
    assert.equal(capturedBody.modelTimestamp, '2026-09-13T14:58:00+00:00');
    assert.equal(capturedBody.modelVersion, 'sia_model_v2026_preseason');
    assert.equal(capturedBody.probabilityEngineVersion, 'empirical_residual_engine_v2026_preseason');
    assert.equal(capturedBody.calibrationVersion, 'guarded_isotonic_v2026_preseason');
    assert.equal(capturedBody.rankingVersion, 'ranking_calibrated_edge_v2026');
    assert.equal(capturedBody.qualificationPolicyVersion, 'qualification_explicit_policy_v2026');
    assert.equal(capturedBody.quoteTimestamp, '2026-09-13T15:00:00+00:00');
    assert.equal(capturedBody.marketTimestamp, '2026-09-13T15:01:00+00:00');
    assert.equal(capturedBody.fullKellyFraction, 0.024);
    assert.equal(capturedBody.fractionalKellyFraction, 0.0048);
    assert.equal(capturedBody.bankrollPercent, 0.48);
    assert.equal(capturedBody.bankrollBasis, 1000);
    assert.equal(capturedBody.currentExecution.sportsbook, 'FanDuel');
    assert.equal(capturedBody.currentSizing.unitSize, 100);
    assert.equal(readCard().length, 1);
    assert.ok(storage.get('sports-intelligence-card'));
  } finally {
    restoreGlobals(originalWindow, originalLocalStorage, originalFetch);
  }
});

test('addToCard treats non-complete tracking responses as failure', async () => {
  const originalWindow = globalThis.window;
  const originalLocalStorage = globalThis.localStorage;
  const originalFetch = globalThis.fetch;

  withWindow();
  globalThis.fetch = async () => {
    return new Response(JSON.stringify({ success: true, trackingStatus: 'PARTIAL', snapshotId: 'snap-partial' }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const result = await addToCard({
      id: 'opp-4',
      season: 2026,
      week: 1,
      eventId: 'evt-4',
      market: 'spread',
      side: 'away',
      pick: 'NO +4',
      point: 4,
      price: -105,
      book: 'FanDuel',
      qualificationStatus: 'QUALIFIED',
      currentExecution: { status: 'AVAILABLE' },
      currentQualification: { status: 'QUALIFIED', actionable: true },
      currentSizing: {
        status: 'AVAILABLE',
        recommendedUnits: 0.5,
        recommendedAmount: 50,
        unitSize: 100,
      },
    });

    assert.equal(result.success, false);
    assert.equal(result.trackingStatus, 'FAILED');
  } finally {
    restoreGlobals(originalWindow, originalLocalStorage, originalFetch);
  }
});

test('addToCard fails closed when a qualified current wager has no sizing', async () => {
  const originalWindow = globalThis.window;
  const originalLocalStorage = globalThis.localStorage;
  const originalFetch = globalThis.fetch;

  withWindow();
  let fetchCalls = 0;
  globalThis.fetch = async () => {
    fetchCalls += 1;
    return new Response(JSON.stringify({ success: true, trackingStatus: 'COMPLETE' }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    const result = await addToCard({
      id: 'opp-2',
      eventId: 'evt-2',
      market: 'spread',
      side: 'away',
      pick: 'NO +4',
      point: 4,
      price: -105,
      book: 'FanDuel',
      qualificationStatus: 'QUALIFIED',
      currentExecution: { status: 'AVAILABLE' },
      currentQualification: { status: 'QUALIFIED', actionable: true },
    });

    assert.equal(result.success, false);
    assert.match(result.error, /Suggested bet size is not currently available/i);
    assert.equal(fetchCalls, 0);
    assert.equal(readCard().length, 0);
  } finally {
    restoreGlobals(originalWindow, originalLocalStorage, originalFetch);
  }
});
