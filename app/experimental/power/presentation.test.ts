import assert from "node:assert/strict";
import test from "node:test";

import { buildProjectionGroups, MARKET_DATA_UNAVAILABLE, signedSpread } from "./presentation.ts";

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