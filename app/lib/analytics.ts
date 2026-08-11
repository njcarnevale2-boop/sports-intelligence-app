type AnalyticsEventPayload = {
  eventType: string;
  page?: string;
  opportunityId?: string;
  userId?: number;
  metadata?: Record<string, unknown>;
};

type AnalyticsEventOptions = {
  page?: string;
  opportunityId?: string;
  userId?: number;
  metadata?: Record<string, unknown>;
};

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

export function buildAnalyticsEventPayload(
  eventType: string,
  options: AnalyticsEventOptions = {},
): AnalyticsEventPayload {
  const payload: AnalyticsEventPayload = {
    eventType,
    metadata: options.metadata ?? {},
  };

  if (options.page) {
    payload.page = options.page;
  }

  if (options.opportunityId) {
    payload.opportunityId = options.opportunityId;
  }

  if (typeof options.userId === 'number') {
    payload.userId = options.userId;
  }

  return payload;
}

export async function trackAnalyticsEvent(
  eventType: string,
  options: AnalyticsEventOptions = {},
  fetcher: Fetcher = fetch,
) {
  const payload = buildAnalyticsEventPayload(eventType, options);

  await fetcher('/api/analytics/events', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });

  return payload;
}
