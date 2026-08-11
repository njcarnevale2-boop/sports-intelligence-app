import test from 'node:test';
import assert from 'node:assert/strict';

import { buildAnalyticsEventPayload, trackAnalyticsEvent } from './analytics.ts';

test('buildAnalyticsEventPayload adds defaults and preserves metadata', () => {
  const payload = buildAnalyticsEventPayload('OpportunityViewed', {
    page: 'opportunity-detail',
    opportunityId: 'abc123',
    userId: 42,
    metadata: { source: 'landing-page' },
  });

  assert.deepEqual(payload, {
    eventType: 'OpportunityViewed',
    page: 'opportunity-detail',
    opportunityId: 'abc123',
    userId: 42,
    metadata: { source: 'landing-page' },
  });
});

test('trackAnalyticsEvent posts the payload with the provided fetcher', async () => {
  const calls = [];

  const fetcher = async (input, init) => {
    calls.push([input, init]);
    return new Response(JSON.stringify({ success: true }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  await trackAnalyticsEvent('MyCardViewed', { page: 'my-card' }, fetcher);

  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], '/api/analytics/events');
  assert.equal(calls[0][1].method, 'POST');
  assert.deepEqual(JSON.parse(calls[0][1].body), {
    eventType: 'MyCardViewed',
    page: 'my-card',
    metadata: {},
  });
});
