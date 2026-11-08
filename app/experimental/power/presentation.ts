export type ProjectionInput = {
  eventId: string;
  awayTeam: string;
  homeTeam: string;
  kickoffUtc: string;
  homeExpectedMargin: number;
  homeFairSpread: number;
};

export type ProjectionView = ProjectionInput & {
  awayFairSpread: number;
  projectedWinner: string;
  started: boolean;
};

export type ProjectionGroups = {
  upcoming: ProjectionView[];
  started: ProjectionView[];
};

export const MARKET_DATA_UNAVAILABLE = "MARKET_DATA_UNAVAILABLE" as const;
export const MAX_MARKET_AGE_MS = 5 * 60 * 1000;

type TimedMarketGame = {
  kickoffUtc: string;
  marketStatus: "AVAILABLE" | "MARKET_DATA_UNAVAILABLE" | "ALREADY_STARTED";
  marketQuotes: { quoteTimestamp: string }[];
};

export function marketExpiryAt(games: TimedMarketGame[], capturedAt: string | null): number | null {
  const capturedMs = capturedAt ? Date.parse(capturedAt) : NaN;
  if (!Number.isFinite(capturedMs)) return null;

  let expiry = capturedMs + MAX_MARKET_AGE_MS;
  let hasQuotes = false;
  for (const game of games) {
    const kickoffMs = Date.parse(game.kickoffUtc);
    if (!Number.isFinite(kickoffMs)) return null;
    if (game.marketStatus === "ALREADY_STARTED" && kickoffMs > capturedMs) return null;
    for (const quote of game.marketQuotes) {
      const quoteMs = Date.parse(quote.quoteTimestamp);
      if (!Number.isFinite(quoteMs) || quoteMs > capturedMs || quoteMs >= kickoffMs) return null;
      expiry = Math.min(expiry, quoteMs + MAX_MARKET_AGE_MS);
      hasQuotes = true;
    }
  }
  return hasQuotes ? expiry : null;
}

export function visibleMarketQuotes<T extends { quoteTimestamp: string }>(
  game: { kickoffUtc: string; marketStatus: TimedMarketGame["marketStatus"]; marketQuotes: T[] },
  capturedAt: string | null,
  expiry: number | null,
  nowMs: number,
): T[] {
  const capturedMs = capturedAt ? Date.parse(capturedAt) : NaN;
  const kickoffMs = Date.parse(game.kickoffUtc);
  if (
    game.marketStatus !== "AVAILABLE" ||
    !Number.isFinite(nowMs) || !Number.isFinite(capturedMs) || !Number.isFinite(kickoffMs) ||
    capturedMs > nowMs || expiry === null || nowMs >= expiry || nowMs >= kickoffMs
  ) return [];
  return game.marketQuotes;
}

type SpreadQuote = {
  quoteTimestamp: string;
  homeSpreadPoint: number;
  awaySpreadPoint: number;
  homePrice: number;
  awayPrice: number;
};

export function spreadSelections<T extends SpreadQuote>(
  game: ProjectionInput & { marketStatus: TimedMarketGame["marketStatus"]; marketQuotes: T[] },
  capturedAt: string | null,
  expiry: number | null,
  nowMs: number,
) {
  const kickoff = Date.parse(game.kickoffUtc);
  if (!Number.isFinite(nowMs) || !Number.isFinite(kickoff)) return { status: MARKET_DATA_UNAVAILABLE, selections: [] };
  if (nowMs >= kickoff) return { status: "NOT_PREGAME" as const, selections: [] };
  if (!Number.isFinite(game.homeFairSpread) || !Number.isFinite(game.homeExpectedMargin) ||
      Math.abs(game.homeFairSpread + game.homeExpectedMargin) > 0.01) {
    return { status: MARKET_DATA_UNAVAILABLE, selections: [] };
  }
  const quotes = visibleMarketQuotes(game, capturedAt, expiry, nowMs);
  const selections = quotes.flatMap((quote) => {
    if (![quote.homeSpreadPoint, quote.awaySpreadPoint, quote.homePrice, quote.awayPrice].every(Number.isFinite) ||
        quote.homePrice === 0 || quote.awayPrice === 0 || Math.abs(quote.homeSpreadPoint + quote.awaySpreadPoint) > 0.01) return [];
    const homeDifference = quote.homeSpreadPoint - game.homeFairSpread;
    const tie = Math.abs(homeDifference) < 1e-9;
    const home = homeDifference > 0;
    return [{
      quote,
      side: tie ? "TIE" as const : home ? "HOME" as const : "AWAY" as const,
      team: tie ? null : home ? game.homeTeam : game.awayTeam,
      sportsbookSpread: home || tie ? quote.homeSpreadPoint : quote.awaySpreadPoint,
      fairSpread: home || tie ? game.homeFairSpread : -game.homeFairSpread,
      pointDifference: tie ? 0 : home ? homeDifference : quote.awaySpreadPoint + game.homeFairSpread,
      price: home || tie ? quote.homePrice : quote.awayPrice,
    }];
  });
  return { status: selections.length ? "AVAILABLE" as const : MARKET_DATA_UNAVAILABLE, selections };
}

export function nextProjectionUpdateAt(games: TimedMarketGame[], capturedAt: string | null, nowMs: number): number | null {
  const deadlines = games.map((game) => Date.parse(game.kickoffUtc));
  const expiry = marketExpiryAt(games, capturedAt);
  if (expiry !== null) deadlines.push(expiry);
  const upcoming = deadlines.filter((deadline) => Number.isFinite(deadline) && deadline > nowMs);
  return upcoming.length ? Math.min(...upcoming) : null;
}

type ClearedMarketData<T extends { games: { marketQuotes: unknown[] }[] }> = Omit<
  T,
  "marketDataStatus" | "marketDataReason" | "marketDataCapturedAt" | "games"
> & {
  marketDataStatus: typeof MARKET_DATA_UNAVAILABLE;
  marketDataReason: "REFRESH_FAILED";
  marketDataCapturedAt: null;
  games: (Omit<T["games"][number], "marketStatus" | "marketQuotes"> & {
    marketStatus: typeof MARKET_DATA_UNAVAILABLE;
    marketQuotes: [];
  })[];
};

export function clearMarketData<T extends { games: { marketQuotes: unknown[] }[] }>(data: T): ClearedMarketData<T> {
  const games = data.games.map((game) => ({
    ...game,
    marketStatus: MARKET_DATA_UNAVAILABLE,
    marketQuotes: [],
  })) as ClearedMarketData<T>["games"];
  return {
    ...data,
    marketDataStatus: MARKET_DATA_UNAVAILABLE,
    marketDataReason: "REFRESH_FAILED",
    marketDataCapturedAt: null,
    games,
  };
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function buildProjectionGroups(games: unknown, nowMs: number): ProjectionGroups {
  if (!Array.isArray(games) || !Number.isFinite(nowMs)) {
    throw new Error("Invalid projection collection or current time");
  }

  const views = games.map((value, index): ProjectionView => {
    if (!value || typeof value !== "object") {
      throw new Error(`Missing projection fields at row ${index}`);
    }
    const game = value as Record<string, unknown>;
    const eventId = typeof game.eventId === "string" ? game.eventId.trim() : "";
    const awayTeam = typeof game.awayTeam === "string" ? game.awayTeam.trim() : "";
    const homeTeam = typeof game.homeTeam === "string" ? game.homeTeam.trim() : "";
    const kickoffUtc = typeof game.kickoffUtc === "string" ? game.kickoffUtc : "";
    const kickoffMs = Date.parse(kickoffUtc);
    if (!eventId || !awayTeam || !homeTeam || !Number.isFinite(kickoffMs)) {
      throw new Error(`Missing event, team, or kickoff fields at row ${index}`);
    }
    if (!finiteNumber(game.homeExpectedMargin) || !finiteNumber(game.homeFairSpread)) {
      throw new Error(`Missing or invalid projected margin/spread at row ${index}`);
    }
    if (Math.abs(game.homeFairSpread + game.homeExpectedMargin) > 0.01) {
      throw new Error(`Home fair spread sign mismatch at row ${index}`);
    }

    return {
      eventId,
      awayTeam,
      homeTeam,
      kickoffUtc,
      homeExpectedMargin: game.homeExpectedMargin,
      homeFairSpread: game.homeFairSpread,
      awayFairSpread: -game.homeFairSpread,
      projectedWinner:
        game.homeExpectedMargin > 0
          ? homeTeam
          : game.homeExpectedMargin < 0
            ? awayTeam
            : "Toss-up",
      started: kickoffMs <= nowMs,
    };
  });

  return {
    upcoming: views.filter((game) => !game.started),
    started: views.filter((game) => game.started),
  };
}

export function formatKickoffUtc(kickoffUtc: string): string {
  const kickoff = new Date(kickoffUtc);
  if (!Number.isFinite(kickoff.getTime())) {
    throw new Error("Invalid kickoff timestamp");
  }
  return `${new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "UTC",
  }).format(kickoff)} UTC`;
}

export function signedSpread(value: number): string {
  if (!Number.isFinite(value)) {
    throw new Error("Spread must be finite");
  }
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}`;
}