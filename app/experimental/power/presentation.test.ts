import assert from "node:assert/strict";
import test from "node:test";

import {
  buildProjectionGroups, clearMarketData, marketExpiryAt, MARKET_DATA_UNAVAILABLE,
  nextProjectionUpdateAt, signedSpread, spreadSelections, visibleMarketQuotes,
} from "./presentation.ts";

const now = Date.parse("2026-11-07T12:00:00Z");

test("fair spread signs match the home-margin convention", () => {
  const groups = buildProjectionGroups(
    [
      {
        eventId: "home-favorite",
        awayTeam: "AWY",
        homeTeam: "HME",
        kickoffUtc: "2026-11-08T18:00:00Z",
        homeExpectedMargin: 3.5,
        homeFairSpread: -3.5,
      },
      {
        eventId: "away-favorite",
        awayTeam: "AWY2",
        homeTeam: "HME2",
        kickoffUtc: "2026-11-08T19:00:00Z",
        homeExpectedMargin: -2.5,
        homeFairSpread: 2.5,
      },
    ],
    now,
  );

  assert.equal(groups.upcoming[0].projectedWinner, "HME");
  assert.equal(signedSpread(groups.upcoming[0].homeFairSpread), "-3.5");
  assert.equal(signedSpread(groups.upcoming[0].awayFairSpread), "+3.5");
  assert.equal(groups.upcoming[1].projectedWinner, "AWY2");
  assert.equal(signedSpread(groups.upcoming[1].homeFairSpread), "+2.5");
  assert.equal(signedSpread(groups.upcoming[1].awayFairSpread), "-2.5");
  assert.equal(MARKET_DATA_UNAVAILABLE, "MARKET_DATA_UNAVAILABLE");
});

test("missing projection fields fail closed", () => {
  assert.throws(
    () => buildProjectionGroups([{ eventId: "missing-margin", awayTeam: "AWY", homeTeam: "HME", kickoffUtc: "2026-11-08T18:00:00Z" }], now),
    /Missing or invalid projected margin\/spread/,
  );
});

test("kickoff boundary separates upcoming and already-started games", () => {
  const groups = buildProjectionGroups(
    [
      { eventId: "past", awayTeam: "AWY", homeTeam: "HME", kickoffUtc: "2026-11-07T11:59:59Z", homeExpectedMargin: 1, homeFairSpread: -1 },
      { eventId: "at-kickoff", awayTeam: "AWY2", homeTeam: "HME2", kickoffUtc: "2026-11-07T12:00:00Z", homeExpectedMargin: -1, homeFairSpread: 1 },
      { eventId: "future", awayTeam: "AWY3", homeTeam: "HME3", kickoffUtc: "2026-11-07T12:00:01Z", homeExpectedMargin: 0, homeFairSpread: 0 },
    ],
    now,
  );

  assert.deepEqual(groups.started.map((game) => game.eventId), ["past", "at-kickoff"]);
  assert.deepEqual(groups.upcoming.map((game) => game.eventId), ["future"]);
});

test("inconsistent spread sign is rejected", () => {
  assert.throws(
    () => buildProjectionGroups([{ eventId: "bad-sign", awayTeam: "AWY", homeTeam: "HME", kickoffUtc: "2026-11-08T18:00:00Z", homeExpectedMargin: 3, homeFairSpread: 3 }], now),
    /Home fair spread sign mismatch/,
  );
});

test("quotes expire at the earliest quote or capture freshness boundary", () => {
  const capturedAt = "2026-11-07T12:00:00Z";
  const game = {
    kickoffUtc: "2026-11-07T13:00:00Z",
    marketStatus: "AVAILABLE" as const,
    marketQuotes: [{ quoteTimestamp: "2026-11-07T11:59:30Z" }],
  };
  const expiry = marketExpiryAt([game], capturedAt);
  assert.equal(expiry, Date.parse("2026-11-07T12:04:30Z"));
  assert.equal(visibleMarketQuotes(game, capturedAt, expiry, expiry! - 1).length, 1);
  assert.deepEqual(visibleMarketQuotes(game, capturedAt, expiry, expiry!), []);
  assert.equal(nextProjectionUpdateAt([game], capturedAt, now), expiry);
});

test("kickoff immediately suppresses quotes and schedules a clock update", () => {
  const capturedAt = "2026-11-07T12:00:00Z";
  const game = {
    kickoffUtc: "2026-11-07T12:01:00Z",
    marketStatus: "AVAILABLE" as const,
    marketQuotes: [{ quoteTimestamp: capturedAt }],
  };
  const expiry = marketExpiryAt([game], capturedAt);
  const kickoff = Date.parse(game.kickoffUtc);
  assert.equal(nextProjectionUpdateAt([game], capturedAt, now), kickoff);
  assert.equal(visibleMarketQuotes(game, capturedAt, expiry, kickoff - 1).length, 1);
  assert.deepEqual(visibleMarketQuotes(game, capturedAt, expiry, kickoff), []);
});

test("a failed refresh clears cached market data but preserves projections", () => {
  const data = {
    marketDataStatus: "AVAILABLE" as const,
    marketDataReason: null,
    marketDataCapturedAt: "2026-11-07T12:00:00Z",
    games: [{ eventId: "game", homeFairSpread: -3.5, marketStatus: "AVAILABLE" as const, marketQuotes: [{ quoteTimestamp: "2026-11-07T12:00:00Z" }] }],
  };
  const cleared = clearMarketData(data);
  assert.equal(cleared.marketDataStatus, MARKET_DATA_UNAVAILABLE);
  assert.equal(cleared.marketDataReason, "REFRESH_FAILED");
  assert.equal(cleared.marketDataCapturedAt, null);
  assert.deepEqual(cleared.games[0].marketQuotes, []);
  assert.equal(cleared.games[0].marketStatus, MARKET_DATA_UNAVAILABLE);
  assert.equal(cleared.games[0].homeFairSpread, -3.5);
});

test("capture with a previously captured started game fails closed", () => {
  const capturedAt = "2026-11-07T12:00:00Z";
  const started = { kickoffUtc: "2026-11-07T12:01:00Z", marketStatus: "ALREADY_STARTED" as const, marketQuotes: [] };
  const upcoming = { kickoffUtc: "2026-11-07T13:00:00Z", marketStatus: "AVAILABLE" as const, marketQuotes: [{ quoteTimestamp: capturedAt }] };
  assert.equal(marketExpiryAt([started, upcoming], capturedAt), null);
});

test("spread selections normalize home and away sides per sportsbook", () => {
  const capturedAt = "2026-11-07T12:00:00Z";
  const baseQuote = { quoteTimestamp: capturedAt, homePrice: -110, awayPrice: -110 };
  const game = {
    eventId: "game", awayTeam: "AWY", homeTeam: "HME", kickoffUtc: "2026-11-07T13:00:00Z",
    homeExpectedMargin: 3, homeFairSpread: -3, marketStatus: "AVAILABLE" as const,
    marketQuotes: [
      { ...baseQuote, sportsbookKey: "home-book", homeSpreadPoint: -2, awaySpreadPoint: 2 },
      { ...baseQuote, sportsbookKey: "away-book", homeSpreadPoint: -4, awaySpreadPoint: 4 },
      { ...baseQuote, sportsbookKey: "tie-book", homeSpreadPoint: -3, awaySpreadPoint: 3 },
    ],
  };
  const result = spreadSelections(game, capturedAt, marketExpiryAt([game], capturedAt), now);
  assert.equal(result.status, "AVAILABLE");
  assert.deepEqual(result.selections.map(({ side, team, sportsbookSpread, fairSpread, pointDifference }) => ({ side, team, sportsbookSpread, fairSpread, pointDifference })), [
    { side: "HOME", team: "HME", sportsbookSpread: -2, fairSpread: -3, pointDifference: 1 },
    { side: "AWAY", team: "AWY", sportsbookSpread: 4, fairSpread: 3, pointDifference: 1 },
    { side: "TIE", team: null, sportsbookSpread: -3, fairSpread: -3, pointDifference: 0 },
  ]);
});

test("spread selections fail closed for missing, quarantined, stale, and started games", () => {
  const capturedAt = "2026-11-07T12:00:00Z";
  const quote = { quoteTimestamp: capturedAt, homeSpreadPoint: -2, awaySpreadPoint: 2, homePrice: -110, awayPrice: -110 };
  const game = { eventId: "game", awayTeam: "AWY", homeTeam: "HME", kickoffUtc: "2026-11-07T12:01:00Z", homeExpectedMargin: 3, homeFairSpread: -3, marketStatus: "AVAILABLE" as const, marketQuotes: [quote] };
  const expiry = marketExpiryAt([game], capturedAt);
  assert.equal(spreadSelections({ ...game, marketQuotes: [] }, capturedAt, expiry, now).status, MARKET_DATA_UNAVAILABLE);
  assert.equal(spreadSelections({ ...game, marketStatus: MARKET_DATA_UNAVAILABLE }, capturedAt, expiry, now).status, MARKET_DATA_UNAVAILABLE);
  assert.equal(spreadSelections(game, capturedAt, expiry, Date.parse(game.kickoffUtc)).status, "NOT_PREGAME");
  assert.equal(spreadSelections({ ...game, kickoffUtc: "2026-11-07T13:00:00Z" }, capturedAt, expiry, expiry!).status, MARKET_DATA_UNAVAILABLE);
  assert.equal(spreadSelections({ ...game, marketQuotes: [{ ...quote, awaySpreadPoint: 9 }] }, capturedAt, expiry, now).status, MARKET_DATA_UNAVAILABLE);
});