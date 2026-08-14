import test from 'node:test';
import assert from 'node:assert/strict';

import {
  formatRestAdvantage,
  formatRestDays,
  formatTravelMiles,
  formatTravelShift,
  getContextReason,
  getInjuryFreshness,
  getRestLabel,
  hasScheduleContext,
  isContextFlagEnabled,
} from './page-context.ts';

test('page context helpers handle complete schedule context', () => {
  const context = {
    eventId: 'evt-1',
    week: 2,
    awayTeam: 'BUF',
    homeTeam: 'MIA',
    rest: {
      label: 'MIA rest advantage',
      awayDays: 5,
      homeDays: 7,
      advantageHomeDays: 2,
      weekOneNeutralized: false,
      shortRestHome: false,
      shortRestAway: true,
      longRestHome: false,
      longRestAway: false,
    },
    travel: {
      awayMiles: 1423.4,
      awayTimezoneShiftHours: 1,
    },
  };

  assert.equal(hasScheduleContext(context), true);
  assert.equal(getRestLabel(context.rest), 'MIA rest advantage');
  assert.equal(formatTravelMiles(context.travel), '1,423.4 mi');
  assert.equal(formatTravelShift(context.travel), '+1h');
  assert.equal(formatRestDays(context.rest, 'away'), '5 days');
  assert.equal(formatRestDays(context.rest, 'home'), '7 days');
  assert.equal(formatRestAdvantage(context.rest), '+2 days');
  assert.equal(isContextFlagEnabled(context.rest.shortRestAway), true);
});

test('page context helpers tolerate missing rest and travel fields', () => {
  const context = {
    eventId: 'evt-2',
    available: false,
    reason: 'Rest and travel context not yet available for this game',
  };

  assert.equal(hasScheduleContext(context), false);
  assert.equal(getRestLabel(context.rest), 'Rest data unavailable');
  assert.equal(formatTravelMiles(context.travel), null);
  assert.equal(formatTravelShift(context.travel), null);
  assert.equal(formatRestDays(context.rest, 'away'), 'N/A');
  assert.equal(formatRestAdvantage(context.rest), 'N/A');
  assert.equal(getContextReason(context), 'Rest and travel context not yet available for this game');
});

test('page context helpers tolerate null context fields and week-one neutralization', () => {
  const context = {
    eventId: 'evt-3',
    week: 1,
    rest: {
      label: null,
      awayDays: null,
      homeDays: null,
      advantageHomeDays: null,
      weekOneNeutralized: true,
      shortRestHome: null,
      shortRestAway: null,
      longRestHome: null,
      longRestAway: null,
    },
    travel: {
      awayMiles: null,
      awayTimezoneShiftHours: null,
    },
  };

  assert.equal(hasScheduleContext(context), true);
  assert.equal(getRestLabel(context.rest), 'Offseason / neutral rest');
  assert.equal(formatRestDays(context.rest, 'away'), 'Offseason');
  assert.equal(formatRestDays(context.rest, 'home'), 'Offseason');
  assert.equal(formatRestAdvantage(context.rest), 'Neutral');
  assert.equal(isContextFlagEnabled(context.rest.shortRestHome), false);
});

test('injury freshness helper tolerates missing and partial injury context', () => {
  assert.equal(getInjuryFreshness(null), null);
  assert.equal(getInjuryFreshness({}), null);
  assert.deepEqual(
    getInjuryFreshness({
      providerMetadata: {
        dataStatus: 'LIVE',
        isLive: true,
        lastUpdated: '2026-09-10T12:00:00Z',
      },
    }),
    {
      dataStatus: 'LIVE',
      isLive: true,
      lastUpdated: '2026-09-10T12:00:00Z',
    },
  );
});