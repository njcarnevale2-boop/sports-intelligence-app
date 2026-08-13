"use client";

import { useEffect, useMemo, useState } from "react";

import { fetchJson } from "../lib/api";
import Tooltip from "@/components/ui/tooltip";

type LineMovement = {
  id: string;
  eventId: string;
  commenceTime: string;
  matchup: string;
  awayTeam: string;
  homeTeam: string;
  sportsbook: string;
  market: string;
  side: string;
  firstSeen: string;
  lastSeen: string;
  openingPoint: number | null;
  latestPoint: number | null;
  pointMove: number | null;
  openingPrice: number | null;
  latestPrice: number | null;
  priceMove: number | null;
  steamFlag: boolean;
  snapshots: number | null;
};

type LineMovementResponse = {
  count: number;
  source: string;
  steamOnly: boolean;
  provider?: string;
  lastUpdated?: string | null;
  dataStatus?: "LIVE" | "CACHED" | "MOCK" | "FILE" | "UNAVAILABLE" | string;
  lineHistory?: {
    openingLineAvailable?: boolean;
    currentLineAvailable?: boolean;
    closingLineAvailable?: boolean;
    historicalSnapshots?: number;
    message?: string;
  };
  summary: {
    steamMoves: number;
    biggestPointMove: number;
  };
  movements: LineMovement[];
};

type MarketFilter =
  | "all"
  | "spreads"
  | "totals"
  | "h2h";

type SortOption =
  | "largest-point"
  | "largest-price"
  | "recent";

function formatOdds(value: number | null) {
  if (value === null) {
    return "—";
  }

  return value > 0 ? `+${value}` : `${value}`;
}

function formatPoint(value: number | null) {
  if (value === null) {
    return "—";
  }

  if (value > 0) {
    return `+${value}`;
  }

  return `${value}`;
}

function formatMove(value: number | null) {
  if (value === null) {
    return "—";
  }

  if (value > 0) {
    return `+${value}`;
  }

  return `${value}`;
}

function marketLabel(market: string) {
  if (market === "spreads") {
    return "Spread";
  }

  if (market === "totals") {
    return "Total";
  }

  if (market === "h2h") {
    return "Moneyline";
  }

  return market;
}

function movementDirection(
  movement: LineMovement
) {
  if (
    movement.pointMove !== null &&
    movement.pointMove !== 0
  ) {
    return movement.pointMove > 0
      ? "Moved Up"
      : "Moved Down";
  }

  if (
    movement.priceMove !== null &&
    movement.priceMove !== 0
  ) {
    return movement.priceMove > 0
      ? "Price Up"
      : "Price Down";
  }

  return "Stable";
}

export default function LineMovementPage() {
  const [movements, setMovements] = useState<
    LineMovement[]
  >([]);
  const [marketMeta, setMarketMeta] = useState<{
    provider?: string;
    lastUpdated?: string | null;
    dataStatus?: string;
    historyMessage?: string;
  }>({});

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [steamOnly, setSteamOnly] =
    useState(false);

  const [marketFilter, setMarketFilter] =
    useState<MarketFilter>("all");

  const [sportsbookFilter, setSportsbookFilter] =
    useState("all");

  const [sortBy, setSortBy] =
    useState<SortOption>("largest-point");

  useEffect(() => {
    async function loadMovement() {
      try {
        setLoading(true);
        setError("");

        const data = await fetchJson<LineMovementResponse>(
          "/api/line-movement?limit=1000"
        );

        setMovements(data.movements);
        setMarketMeta({
          provider: data.provider,
          lastUpdated: data.lastUpdated,
          dataStatus: data.dataStatus,
          historyMessage: data.lineHistory?.message,
        });
      } catch (err) {
        console.error(err);

        setError(
          "Unable to load market movement."
        );
      } finally {
        setLoading(false);
      }
    }

    loadMovement();
  }, []);

  const sportsbooks = useMemo(() => {
    return Array.from(
      new Set(
        movements.map(
          (movement) => movement.sportsbook
        )
      )
    ).sort();
  }, [movements]);

  const filteredMovements = useMemo(() => {
    let filtered = [...movements];

    if (steamOnly) {
      filtered = filtered.filter(
        (movement) => movement.steamFlag
      );
    }

    if (marketFilter !== "all") {
      filtered = filtered.filter(
        (movement) =>
          movement.market === marketFilter
      );
    }

    if (sportsbookFilter !== "all") {
      filtered = filtered.filter(
        (movement) =>
          movement.sportsbook ===
          sportsbookFilter
      );
    }

    filtered.sort((a, b) => {
      if (sortBy === "largest-point") {
        const aMove = Math.abs(
          a.pointMove ?? 0
        );

        const bMove = Math.abs(
          b.pointMove ?? 0
        );

        return bMove - aMove;
      }

      if (sortBy === "largest-price") {
        const aMove = Math.abs(
          a.priceMove ?? 0
        );

        const bMove = Math.abs(
          b.priceMove ?? 0
        );

        return bMove - aMove;
      }

      return (
        new Date(b.lastSeen).getTime() -
        new Date(a.lastSeen).getTime()
      );
    });

    return filtered;
  }, [
    movements,
    steamOnly,
    marketFilter,
    sportsbookFilter,
    sortBy,
  ]);

  const steamCount = useMemo(() => {
    return movements.filter(
      (movement) => movement.steamFlag
    ).length;
  }, [movements]);

  const biggestPointMove = useMemo(() => {
    const values = movements
      .map((movement) =>
        Math.abs(movement.pointMove ?? 0)
      )
      .filter((value) => value > 0);

    if (values.length === 0) {
      return 0;
    }

    return Math.max(...values);
  }, [movements]);

  const activeGames = useMemo(() => {
    return new Set(
      movements.map(
        (movement) => movement.eventId
      )
    ).size;
  }, [movements]);

  const latestSnapshot = useMemo(() => {
    if (movements.length === 0) {
      return null;
    }

    return movements.reduce(
      (latest, movement) => {
        const currentTime = new Date(
          movement.lastSeen
        ).getTime();

        const latestTime = new Date(
          latest
        ).getTime();

        return currentTime > latestTime
          ? movement.lastSeen
          : latest;
      },
      movements[0].lastSeen
    );
  }, [movements]);

  if (loading) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-7xl px-6 py-16 lg:px-10">
          <p className="text-sm text-zinc-500">
            Loading live market movement...
          </p>
        </div>
      </main>
    );
  }

  if (error) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-7xl px-6 py-16 lg:px-10">
          <p className="text-red-400">
            {error}
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-7xl px-6 py-10 lg:px-10">

        {/* HEADER */}

        <section>
          <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-[0.2em] text-emerald-400">
                Market Intelligence
              </p>

              <h1 className="mt-3 text-4xl font-semibold tracking-[-0.03em] md:text-6xl">
                Line Movement
              </h1>

              <p className="mt-5 max-w-3xl text-base leading-7 text-zinc-500">
                Track opening numbers,
                current prices, steam moves,
                and sportsbook movement across
                the NFL market.
              </p>
            </div>

            <div className="rounded-full border border-emerald-400/20 bg-emerald-400/[0.05] px-4 py-2 text-sm text-emerald-400">
              {marketMeta.dataStatus ?? "UNAVAILABLE"} • {marketMeta.provider ?? "Unknown provider"}
            </div>
          </div>
        </section>

        {/* TOP METRICS */}

        <section className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Market Outcomes
            </p>

            <p className="mt-3 text-3xl font-semibold">
              {movements.length}
            </p>
          </div>

          <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700 inline-flex items-center">
              Steam Moves
              <Tooltip term="Steam" />
            </p>

            <p className="mt-3 text-3xl font-semibold text-emerald-400">
              {steamCount}
            </p>
          </div>

          <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Biggest Move
            </p>

            <p className="mt-3 text-3xl font-semibold">
              {biggestPointMove.toFixed(1)} pts
            </p>
          </div>

          <div className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Games Tracked
            </p>

            <p className="mt-3 text-3xl font-semibold">
              {activeGames}
            </p>
          </div>
        </section>

        {/* MARKET STATUS */}

        <section className="mt-6 rounded-3xl border border-white/[0.07] bg-[#0B1119] p-6">
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <p className="text-xs uppercase tracking-[0.16em] text-zinc-700">
                Market Status
              </p>

              <p className="mt-2 text-lg font-medium">
                {steamCount > 0
                  ? `${steamCount} significant movements detected`
                  : "No significant movement detected"}
              </p>
            </div>

            {latestSnapshot && (
              <div className="text-sm text-zinc-600">
                Last snapshot:{" "}
                {new Date(
                  latestSnapshot
                ).toLocaleString()}
              </div>
            )}
          </div>
          {marketMeta.historyMessage ? (
            <p className="mt-4 text-sm text-zinc-500">{marketMeta.historyMessage}</p>
          ) : null}
        </section>

        {/* FILTERS */}

        <section className="mt-6 rounded-3xl border border-white/[0.07] bg-[#0B1119] p-5">
          <div className="grid gap-4 md:grid-cols-4">

            <div>
              <label className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                Market
              </label>

              <select
                value={marketFilter}
                onChange={(event) =>
                  setMarketFilter(
                    event.target
                      .value as MarketFilter
                  )
                }
                className="mt-2 h-11 w-full rounded-xl border border-white/[0.08] bg-[#0D131C] px-4 text-sm text-white outline-none"
              >
                <option value="all">
                  All Markets
                </option>

                <option value="spreads">
                  Spreads
                </option>

                <option value="totals">
                  Totals
                </option>

                <option value="h2h">
                  Moneyline
                </option>
              </select>
            </div>

            <div>
              <label className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                Sportsbook
              </label>

              <select
                value={sportsbookFilter}
                onChange={(event) =>
                  setSportsbookFilter(
                    event.target.value
                  )
                }
                className="mt-2 h-11 w-full rounded-xl border border-white/[0.08] bg-[#0D131C] px-4 text-sm text-white outline-none"
              >
                <option value="all">
                  All Sportsbooks
                </option>

                {sportsbooks.map((book) => (
                  <option
                    key={book}
                    value={book}
                  >
                    {book}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                Sort
              </label>

              <select
                value={sortBy}
                onChange={(event) =>
                  setSortBy(
                    event.target
                      .value as SortOption
                  )
                }
                className="mt-2 h-11 w-full rounded-xl border border-white/[0.08] bg-[#0D131C] px-4 text-sm text-white outline-none"
              >
                <option value="largest-point">
                  Largest Point Move
                </option>

                <option value="largest-price">
                  Largest Price Move
                </option>

                <option value="recent">
                  Most Recent
                </option>
              </select>
            </div>

            <div>
              <label className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                Signal
              </label>

              <button
                onClick={() =>
                  setSteamOnly(
                    (current) => !current
                  )
                }
                className={`mt-2 flex h-11 w-full items-center justify-center rounded-xl border text-sm font-medium transition ${
                  steamOnly
                    ? "border-emerald-400/30 bg-emerald-400/[0.08] text-emerald-400"
                    : "border-white/[0.08] bg-[#0D131C] text-zinc-400 hover:text-white"
                }`}
              >
                {steamOnly
                  ? "Steam Only ✓"
                  : "Show Steam Only"}
              </button>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] pt-4">
            <p className="text-sm text-zinc-500">
              Showing{" "}
              <span className="font-medium text-white">
                {filteredMovements.length}
              </span>{" "}
              market outcomes
            </p>

            {(marketFilter !== "all" ||
              sportsbookFilter !== "all" ||
              steamOnly ||
              sortBy !==
                "largest-point") && (
              <button
                onClick={() => {
                  setMarketFilter("all");
                  setSportsbookFilter("all");
                  setSteamOnly(false);
                  setSortBy(
                    "largest-point"
                  );
                }}
                className="text-sm text-zinc-600 transition hover:text-white"
              >
                Reset filters
              </button>
            )}
          </div>
        </section>

        {/* MOVEMENT CARDS */}

        <section className="mt-8 space-y-4">
          {filteredMovements.map(
            (movement) => {
              const direction =
                movementDirection(
                  movement
                );

              return (
                <article
                  key={movement.id}
                  className={`rounded-3xl border p-7 ${
                    movement.steamFlag
                      ? "border-emerald-400/15 bg-[linear-gradient(135deg,#101814_0%,#0D131C_100%)]"
                      : "border-white/[0.07] bg-[#0D131C]"
                  }`}
                >
                  <div className="flex flex-col gap-7 lg:flex-row lg:items-center lg:justify-between">

                    {/* GAME INFO */}

                    <div className="min-w-[250px]">
                      <div className="flex flex-wrap items-center gap-2">
                        {movement.steamFlag && (
                          <span className="rounded-full border border-emerald-400/20 bg-emerald-400/[0.08] px-3 py-1 text-[10px] font-semibold uppercase tracking-wider text-emerald-400">
                            Steam
                          </span>
                        )}

                        <span className="rounded-full border border-white/[0.08] px-3 py-1 text-[10px] uppercase tracking-wider text-zinc-500">
                          {marketLabel(
                            movement.market
                          )}
                        </span>
                      </div>

                      <p className="mt-5 text-sm text-zinc-500">
                        {movement.matchup}
                      </p>

                      <h2 className="mt-1 text-2xl font-semibold">
                        {movement.sportsbook}
                      </h2>

                      <p className="mt-2 text-sm capitalize text-zinc-600">
                        {movement.side}
                      </p>
                    </div>

                    {/* LINE MOVE */}

                    <div className="grid flex-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
                      <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                        <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                          Open
                        </p>

                        <p className="mt-2 text-lg font-semibold">
                          {movement.market ===
                          "h2h"
                            ? formatOdds(
                                movement.openingPrice
                              )
                            : formatPoint(
                                movement.openingPoint
                              )}
                        </p>
                      </div>

                      <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                        <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                          Current
                        </p>

                        <p className="mt-2 text-lg font-semibold">
                          {movement.market ===
                          "h2h"
                            ? formatOdds(
                                movement.latestPrice
                              )
                            : formatPoint(
                                movement.latestPoint
                              )}
                        </p>
                      </div>

                      <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                        <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                          Point Move
                        </p>

                        <p
                          className={`mt-2 text-lg font-semibold ${
                            movement.pointMove &&
                            movement.pointMove !==
                              0
                              ? "text-emerald-400"
                              : ""
                          }`}
                        >
                          {formatMove(
                            movement.pointMove
                          )}
                        </p>
                      </div>

                      <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                        <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                          Price Move
                        </p>

                        <p className="mt-2 text-lg font-semibold">
                          {formatMove(
                            movement.priceMove
                          )}
                        </p>
                      </div>

                      <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                        <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                          Snapshots
                        </p>

                        <p className="mt-2 text-lg font-semibold">
                          {movement.snapshots ??
                            "—"}
                        </p>
                      </div>
                    </div>
                  </div>

                  {/* MOVEMENT FOOTER */}

                  <div className="mt-6 flex flex-col gap-3 border-t border-white/[0.06] pt-5 md:flex-row md:items-center md:justify-between">
                    <div className="flex flex-wrap items-center gap-4 text-sm">
                      <span className="text-zinc-600">
                        Signal
                      </span>

                      <span
                        className={
                          movement.steamFlag
                            ? "font-medium text-emerald-400"
                            : "font-medium text-zinc-400"
                        }
                      >
                        {movement.steamFlag
                          ? "Significant Movement"
                          : "Normal Market Activity"}
                      </span>

                      <span className="text-zinc-700">
                        •
                      </span>

                      <span className="text-zinc-500">
                        {direction}
                      </span>
                    </div>

                    <div className="text-xs text-zinc-700">
                      {new Date(
                        movement.firstSeen
                      ).toLocaleString()}{" "}
                      →{" "}
                      {new Date(
                        movement.lastSeen
                      ).toLocaleString()}
                    </div>
                  </div>
                </article>
              );
            }
          )}
        </section>

        {filteredMovements.length === 0 && (
          <section className="mt-8 rounded-3xl border border-white/[0.08] bg-[#0D131C] p-8">
            <h2 className="text-2xl font-semibold">
              No market movements match
              these filters.
            </h2>

            <p className="mt-3 text-sm text-zinc-500">
              Reset the filters to return to
              the complete movement board.
            </p>

            <button
              onClick={() => {
                setMarketFilter("all");
                setSportsbookFilter("all");
                setSteamOnly(false);
                setSortBy(
                  "largest-point"
                );
              }}
              className="mt-6 rounded-lg bg-white px-5 py-3 text-sm font-medium text-black transition hover:bg-zinc-200"
            >
              Reset Filters
            </button>
          </section>
        )}
      </div>
    </main>
  );
}