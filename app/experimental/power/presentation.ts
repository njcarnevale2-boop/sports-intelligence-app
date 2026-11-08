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