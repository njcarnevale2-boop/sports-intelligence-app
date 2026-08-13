"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import GameIntelligenceCard from "@/components/game-intelligence-card";
import { fetchJson } from "../lib/api";
import { trackAnalyticsEvent } from "../lib/analytics";
import { addToCard as addToCardWithSnapshot } from "@/lib/add-to-card";
import FreshnessBadge from "@/components/ui/freshness-badge";
import Tooltip from "@/components/ui/tooltip";

type AlternateBook = {
  book: string;
  point: number;
  price: number;
  edge: number;
  evPerDollar: number;
};

type MarketIntelligence = {
  score: number;
  grade: string;
  signal: string;
  booksTracked: number;
  booksMoving: number;
  steamBooks: number;
  supportingBooks: number;
  opposingBooks: number;
  consensus: number;
  largestPointMove: number;
  largestPriceMove: number;
  marketSupport: boolean;
  snapshots: number;
};

type SportsIntelligenceScore = {
  score: number;
  grade: string;
  stars: number;
  recommendation: string;

  components: {
    modelEdge: number;
    expectedValue: number;
    confidence: number;
    marketIntelligence: number;
    dataCompleteness: number;
  };

  weights: {
    modelEdge: number;
    expectedValue: number;
    confidence: number;
    marketIntelligence: number;
    dataCompleteness: number;
  };

  reasons: string[];
};

type Opportunity = {
  id: string;
  eventId: string;
  commenceTime: string;

  matchup: string;
  awayTeam: string;
  homeTeam: string;

  pick: string;
  book: string;

  market: string;
  side: string;

  point: number;
  price: number;

  modelProbability: number;
  impliedProbability: number;

  fairOdds: number;
  edge: number;

  evPerDollar: number;

  kellyFull: number;
  kelly20: number;

  recommendation: string;
  confidence: number;

  dataCompleteness: number;
  marketConfidence: number;
  modelConfidence: number;

  rank: number;
  weekRank?: number;

  marketIntelligence: MarketIntelligence;

  sportsIntelligenceScore: SportsIntelligenceScore;

  alternateBooks?: AlternateBook[];
};

type OpportunitiesResponse = {
  count: number;
  week?: number;
  weekScheduledGames?: number;
  weekQualifiedOpportunities?: number;
  availableWeeks?: number[];
  source: string;
  bestLinesOnly: boolean;
  provider?: string;
  dataStatus?: string;
  lastUpdated?: string | null;
  opportunities: Opportunity[];
};

type SortOption =
  | "rank"
  | "sportsScore"
  | "edge"
  | "ev"
  | "confidence"
  | "marketScore";

function marketAppearance(score: number) {
  if (score >= 8) {
    return {
      text: "text-emerald-400",
      border:
        "border-emerald-400/20 bg-emerald-400/[0.04]",
    };
  }

  if (score >= 6) {
    return {
      text: "text-sky-400",
      border:
        "border-sky-400/20 bg-sky-400/[0.04]",
    };
  }

  if (score >= 4) {
    return {
      text: "text-amber-400",
      border:
        "border-amber-400/20 bg-amber-400/[0.04]",
    };
  }

  return {
    text: "text-zinc-500",
    border:
      "border-white/[0.07] bg-black/10",
  };
}

export default function OpportunitiesPage() {
  const [opportunities, setOpportunities] =
    useState<Opportunity[]>([]);

  const [freshness, setFreshness] =
    useState<{ dataStatus?: string; lastUpdated?: string | null }>({});

  const [loading, setLoading] =
    useState(true);

  const [error, setError] =
    useState("");

  const [sortBy, setSortBy] =
    useState<SortOption>("rank");

  const [
    sportsbookFilter,
    setSportsbookFilter,
  ] = useState("all");

  const [
    marketFilter,
    setMarketFilter,
  ] = useState("all");

  const [added, setAdded] =
    useState<string[]>([]);

  const [snapshotErrors, setSnapshotErrors] =
    useState<Record<string, string>>({});

  const [week, setWeek] = useState<number | null>(null);
  const [availableWeeks, setAvailableWeeks] = useState<number[]>([]);
  const [weekScheduledGames, setWeekScheduledGames] = useState<number>(0);
  const [weekQualifiedOpportunities, setWeekQualifiedOpportunities] = useState<number>(0);

  function changeWeek(w: number) {
    setWeek(w);
  }

  useEffect(() => {
    async function loadOpportunities() {
      try {
        setLoading(true);
        setError("");

        void trackAnalyticsEvent("OpportunitiesViewed", { page: "opportunities" });

        const query = new URLSearchParams({ limit: "100" });
        if (week !== null) query.set("week", String(week));

        const data = await fetchJson<OpportunitiesResponse>(
          `/api/opportunities?${query.toString()}`
        );

        setOpportunities(data.opportunities);
        setFreshness({ dataStatus: data.dataStatus, lastUpdated: data.lastUpdated });
        if (data.availableWeeks?.length) {
          setAvailableWeeks((prev) => data.availableWeeks!.length >= prev.length ? data.availableWeeks! : prev);
        }
        if (week === null && data.week != null) setWeek(data.week);
        if (data.weekScheduledGames != null) setWeekScheduledGames(data.weekScheduledGames);
        if (data.weekQualifiedOpportunities != null) setWeekQualifiedOpportunities(data.weekQualifiedOpportunities);

        const saved =
          localStorage.getItem(
            "sports-intelligence-card"
          );

        if (saved) {
          try {
            const savedCard: Opportunity[] =
              JSON.parse(saved);

            setAdded(
              savedCard.map(
                (item) => item.id
              )
            );
          } catch {
            setAdded([]);
          }
        }
      } catch (err) {
        console.error(err);

        setError(
          "Unable to load model opportunities."
        );
      } finally {
        setLoading(false);
      }
    }

    loadOpportunities();
  }, [week]);

  async function addToCard(
    opportunity: Opportunity
  ) {
    const alreadyAdded = added.includes(opportunity.id);
    if (!alreadyAdded) {
      const result = await addToCardWithSnapshot(opportunity as Record<string, unknown>);
      if (!result.success) {
        setSnapshotErrors((prev) => ({ ...prev, [opportunity.id]: result.error }));
      } else {
        // Clear any prior error on re-add
        setSnapshotErrors((prev) => { const next = { ...prev }; delete next[opportunity.id]; return next; });
      }
    }

    setAdded((current) =>
      current.includes(opportunity.id)
        ? current
        : [...current, opportunity.id]
    );
  }

  const sportsbooks =
    useMemo(() => {
      return Array.from(
        new Set(
          opportunities.map(
            (item) => item.book
          )
        )
      ).sort();
    }, [opportunities]);

  const markets =
    useMemo(() => {
      return Array.from(
        new Set(
          opportunities.map(
            (item) => item.market
          )
        )
      ).sort();
    }, [opportunities]);

  const filteredOpportunities =
    useMemo(() => {
      const filtered =
        opportunities.filter(
          (item) => {
            const sportsbookMatch =
              sportsbookFilter ===
                "all" ||
              item.book ===
                sportsbookFilter;

            const marketMatch =
              marketFilter === "all" ||
              item.market ===
                marketFilter;

            return (
              sportsbookMatch &&
              marketMatch
            );
          }
        );

      return [...filtered].sort(
        (a, b) => {
          if (
            sortBy ===
            "sportsScore"
          ) {
            return (
              b
                .sportsIntelligenceScore
                .score -
              a
                .sportsIntelligenceScore
                .score
            );
          }

          if (
            sortBy === "edge"
          ) {
            return (
              b.edge - a.edge
            );
          }

          if (
            sortBy === "ev"
          ) {
            return (
              b.evPerDollar -
              a.evPerDollar
            );
          }

          if (
            sortBy ===
            "confidence"
          ) {
            return (
              b.confidence -
              a.confidence
            );
          }

          if (
            sortBy ===
            "marketScore"
          ) {
            return (
              b
                .marketIntelligence
                .score -
              a
                .marketIntelligence
                .score
            );
          }

          return (
            a.rank - b.rank
          );
        }
      );
    }, [
      opportunities,
      sportsbookFilter,
      marketFilter,
      sortBy,
    ]);

  const strongestEdge =
    filteredOpportunities.length >
    0
      ? Math.max(
          ...filteredOpportunities.map(
            (item) => item.edge
          )
        )
      : 0;

  const highestConfidence =
    filteredOpportunities.length >
    0
      ? Math.max(
          ...filteredOpportunities.map(
            (item) =>
              item.confidence
          )
        )
      : 0;

  const highestMarketScore =
    filteredOpportunities.length >
    0
      ? Math.max(
          ...filteredOpportunities.map(
            (item) =>
              item
                .marketIntelligence
                .score
          )
        )
      : 0;

  const highestSportsScore =
    filteredOpportunities.length >
    0
      ? Math.max(
          ...filteredOpportunities.map(
            (item) =>
              item
                .sportsIntelligenceScore
                .score
          )
        )
      : 0;

  if (loading) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:px-10">
          <p className="text-sm text-zinc-500">
            Loading model
            opportunities...
          </p>
        </div>
      </main>
    );
  }

  if (error) {
    return (
      <main className="min-h-screen bg-[#070A0F] text-white">
        <div className="mx-auto max-w-6xl px-6 py-16 lg:px-10">
          <p className="text-red-400">
            {error}
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-6xl px-6 py-10 lg:px-10">

        {/* HEADER */}

        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.2em] text-zinc-600">
              Sports Intelligence
              Opportunities
            </p>

            <h1 className="mt-3 text-4xl font-semibold tracking-[-0.03em] md:text-6xl">
              Week {week ?? "…"} opportunities.
            </h1>

            <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-zinc-500">
              {weekScheduledGames > 0 && <span>{weekScheduledGames} games analyzed</span>}
              {weekQualifiedOpportunities > 0 && (
                <span className="text-emerald-400">{weekQualifiedOpportunities} qualified {weekQualifiedOpportunities === 1 ? "opportunity" : "opportunities"}</span>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {/* Week navigation */}
            {availableWeeks.length > 0 && week !== null && (
              <div className="flex items-center gap-1">
                <button
                  onClick={() => { const i = availableWeeks.indexOf(week); if (i > 0) changeWeek(availableWeeks[i - 1]); }}
                  disabled={availableWeeks.indexOf(week) <= 0}
                  className="flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] text-sm text-zinc-400 transition hover:bg-white/[0.08] disabled:opacity-30 disabled:cursor-not-allowed"
                  aria-label="Previous week"
                >‹</button>
                <select
                  value={week}
                  onChange={(e) => changeWeek(Number(e.target.value))}
                  className="h-9 rounded-lg border border-white/10 bg-[#0D131C] px-3 text-sm font-medium text-white outline-none"
                >
                  {availableWeeks.map((w) => <option key={w} value={w}>Week {w}</option>)}
                </select>
                <button
                  onClick={() => { const i = availableWeeks.indexOf(week); if (i < availableWeeks.length - 1) changeWeek(availableWeeks[i + 1]); }}
                  disabled={availableWeeks.indexOf(week) >= availableWeeks.length - 1}
                  className="flex h-9 w-9 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] text-sm text-zinc-400 transition hover:bg-white/[0.08] disabled:opacity-30 disabled:cursor-not-allowed"
                  aria-label="Next week"
                >›</button>
              </div>
            )}
            <Link
              href="/my-card"
              className="flex h-11 items-center justify-center rounded-lg border border-white/10 bg-transparent px-5 text-sm font-medium text-white transition hover:bg-white/[0.05]"
            >
              View My Card →
            </Link>
            {freshness.dataStatus && (
              <FreshnessBadge
                status={freshness.dataStatus}
                lastUpdated={freshness.lastUpdated}
                label="Model"
              />
            )}
          </div>
        </div>

        {/* THIN-WEEK NOTICE */}
        {!loading && weekQualifiedOpportunities > 0 && weekQualifiedOpportunities < 4 && (
          <div className="mt-5 rounded-2xl border border-sky-400/20 bg-sky-400/[0.04] px-5 py-4 text-sm text-sky-300">
            SIA has identified {weekQualifiedOpportunities} qualifying {weekQualifiedOpportunities === 1 ? "opportunity" : "opportunities"} for Week {week}. Additional opportunities may emerge as market, injury, and weather information develops closer to kickoff.
          </div>
        )}

        {/* FILTERS */}

        <section className="mt-8 rounded-3xl border border-white/[0.07] bg-[#0B1119] p-5">
          <div className="grid gap-4 md:grid-cols-3">

            <div>
              <label className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                Sort By
              </label>

              <select
                value={sortBy}
                onChange={(
                  event
                ) =>
                  setSortBy(
                    event.target
                      .value as SortOption
                  )
                }
                className="mt-2 h-11 w-full rounded-xl border border-white/[0.08] bg-[#0D131C] px-4 text-sm text-white outline-none"
              >
                <option value="rank">
                  Model Rank
                </option>

                <option value="sportsScore">
                  Sports Intelligence
                  Score
                </option>

                <option value="edge">
                  Highest Edge
                </option>

                <option value="ev">
                  Highest EV
                </option>

                <option value="confidence">
                  Highest Confidence
                </option>

                <option value="marketScore">
                  Market Intelligence
                </option>
              </select>
            </div>

            <div>
              <label className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                Sportsbook
              </label>

              <select
                value={
                  sportsbookFilter
                }
                onChange={(
                  event
                ) =>
                  setSportsbookFilter(
                    event.target
                      .value
                  )
                }
                className="mt-2 h-11 w-full rounded-xl border border-white/[0.08] bg-[#0D131C] px-4 text-sm text-white outline-none"
              >
                <option value="all">
                  All Sportsbooks
                </option>

                {sportsbooks.map(
                  (book) => (
                    <option
                      key={book}
                      value={book}
                    >
                      {book}
                    </option>
                  )
                )}
              </select>
            </div>

            <div>
              <label className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                Market
              </label>

              <select
                value={
                  marketFilter
                }
                onChange={(
                  event
                ) =>
                  setMarketFilter(
                    event.target
                      .value
                  )
                }
                className="mt-2 h-11 w-full rounded-xl border border-white/[0.08] bg-[#0D131C] px-4 text-sm capitalize text-white outline-none"
              >
                <option value="all">
                  All Markets
                </option>

                {markets.map(
                  (market) => (
                    <option
                      key={
                        market
                      }
                      value={
                        market
                      }
                    >
                      {market}
                    </option>
                  )
                )}
              </select>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.06] pt-4">
            <p className="text-sm text-zinc-500">
              Showing{" "}
              <span className="font-medium text-zinc-200">
                {
                  filteredOpportunities.length
                }
              </span>{" "}
              of{" "}
              {
                opportunities.length
              }{" "}
              opportunities
            </p>

            {(sportsbookFilter !==
              "all" ||
              marketFilter !==
                "all" ||
              sortBy !==
                "rank") && (
              <button
                onClick={() => {
                  setSortBy(
                    "rank"
                  );

                  setSportsbookFilter(
                    "all"
                  );

                  setMarketFilter(
                    "all"
                  );
                }}
                className="text-sm text-zinc-600 transition hover:text-white"
              >
                Reset filters
              </button>
            )}
          </div>
        </section>

        {/* BOARD SUMMARY */}

        <div className="mt-8 grid gap-5 border-y border-white/[0.07] py-5 sm:grid-cols-2 lg:grid-cols-5">

          <div>
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Results
            </p>

            <p className="mt-1 text-xl font-semibold">
              {
                filteredOpportunities.length
              }
            </p>
          </div>

          <div>
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Best SI Score
            </p>

            <p className="mt-1 text-xl font-semibold text-emerald-400">
              {highestSportsScore.toFixed(
                1
              )}
              <span className="text-sm text-zinc-600">
                /100
              </span>
            </p>
          </div>

          <div>
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Strongest Edge
            </p>

            <p className="mt-1 text-xl font-semibold">
              +
              {strongestEdge.toFixed(
                1
              )}
              %
            </p>
          </div>

          <div>
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Highest Confidence
            </p>

            <p className="mt-1 text-xl font-semibold">
              {
                highestConfidence
              }
            </p>
          </div>

          <div>
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Best Market Score
            </p>

            <p className="mt-1 text-xl font-semibold">
              {highestMarketScore.toFixed(
                1
              )}
              <span className="text-sm text-zinc-600">
                /10
              </span>
            </p>
          </div>
        </div>

        {/* OPPORTUNITY CARDS */}

        <section className="mt-8 space-y-5">
          {filteredOpportunities.map(
            (opportunity) => {
              const isAdded =
                added.includes(
                  opportunity.id
                );

              const market =
                opportunity
                  .marketIntelligence;

              const sportsScore =
                opportunity
                  .sportsIntelligenceScore;

              const appearance =
                marketAppearance(
                  market.score
                );

              return (
                <article
                  key={
                    opportunity.id
                  }
                  className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7 md:p-8"
                >
                  <div className="flex flex-col gap-8 lg:flex-row lg:items-start lg:justify-between">

                    {/* LEFT */}

                    <div className="max-w-2xl flex-1">

                      <div className="flex flex-wrap items-center gap-3">

                        <span className="text-xs text-zinc-700">
                          #
                          {opportunity.weekRank ?? opportunity.rank}
                        </span>

                        <Badge
                          variant="outline"
                          className="border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-400"
                        >
                          {opportunity.sportsIntelligenceScore.recommendation}
                        </Badge>

                        <Badge
                          variant="outline"
                          className="border-white/[0.08] bg-white/[0.03] text-zinc-300"
                        >
                          SI{" "}
                          {
                            sportsScore.grade
                          }
                        </Badge>

                        <Badge
                          variant="outline"
                          className={`${appearance.border} ${appearance.text}`}
                        >
                          Market{" "}
                          {
                            market.grade
                          }
                        </Badge>
                      </div>

                      <p className="mt-5 text-sm text-zinc-500">
                        {
                          opportunity.matchup
                        }
                      </p>

                      <h2 className="mt-1 text-3xl font-semibold tracking-tight">
                        {
                          opportunity.pick
                        }
                      </h2>

                      <p className="mt-1 text-sm text-zinc-600">
                        {
                          opportunity.book
                        }{" "}
                        •{" "}
                        {opportunity.price >
                        0
                          ? "+"
                          : ""}
                        {
                          opportunity.price
                        }
                      </p>

                      {/* SPORTS INTELLIGENCE */}

                      <div className="mt-5">
                        <div className="rounded-2xl border border-white/[0.07] bg-black/10 p-4">
                          <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-700 inline-flex items-center">Sports Intelligence Score<Tooltip term="SI Score" /></p>
                          <p className="mt-2 text-3xl font-semibold text-emerald-400">{sportsScore.score.toFixed(1)}</p>
                          <p className="mt-2 text-sm text-zinc-500">{sportsScore.grade}</p>
                        </div>
                      </div>

                      {/* MODEL */}

                      <div className="mt-4 grid gap-3 sm:grid-cols-3">

                        <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                          <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                            Model
                            Probability
                          </p>

                          <p className="mt-2 font-semibold">
                            {opportunity.modelProbability.toFixed(
                              1
                            )}
                            %
                          </p>
                        </div>

                        <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                          <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                            Market
                            Implied
                          </p>

                          <p className="mt-2 font-semibold">
                            {opportunity.impliedProbability.toFixed(
                              1
                            )}
                            %
                          </p>
                        </div>

                        <div className="rounded-xl border border-white/[0.07] bg-black/10 p-4">
                          <p className="text-[10px] uppercase tracking-wider text-zinc-700 inline-flex items-center">
                            EV / $1<Tooltip term="EV" />
                          </p>

                          <p className="mt-2 font-semibold text-emerald-400">
                            +$
                            {opportunity.evPerDollar.toFixed(
                              3
                            )}
                          </p>
                        </div>
                      </div>

                      {/* MARKET INTELLIGENCE */}

                      <div
                        className={`mt-4 rounded-2xl border p-5 ${appearance.border}`}
                      >
                        <div className="flex flex-wrap items-center justify-between gap-4">

                          <div>
                            <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-600">
                              Market
                              Intelligence
                            </p>

                            <p
                              className={`mt-2 text-lg font-semibold ${appearance.text}`}
                            >
                              {
                                market.signal
                              }
                            </p>
                          </div>

                          <div className="text-right">
                            <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-700">
                              Score
                            </p>

                            <div className="mt-1 flex items-baseline justify-end gap-1">

                              <span
                                className={`text-3xl font-semibold ${appearance.text}`}
                              >
                                {market.score.toFixed(
                                  1
                                )}
                              </span>

                              <span className="text-sm text-zinc-600">
                                /10
                              </span>
                            </div>
                          </div>
                        </div>

                        <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">

                          <div className="rounded-xl border border-white/[0.06] bg-black/10 p-3">
                            <p className="text-[9px] uppercase tracking-wider text-zinc-700">
                              Books
                              Moving
                            </p>

                            <p className="mt-2 font-semibold">
                              {
                                market.booksMoving
                              }
                              <span className="text-zinc-600">
                                {" "}
                                /{" "}
                                {
                                  market.booksTracked
                                }
                              </span>
                            </p>
                          </div>

                          <div className="rounded-xl border border-white/[0.06] bg-black/10 p-3">
                            <p className="text-[9px] uppercase tracking-wider text-zinc-700">
                              Steam
                              Books
                            </p>

                            <p
                              className={`mt-2 font-semibold ${
                                market.steamBooks >
                                0
                                  ? "text-emerald-400"
                                  : ""
                              }`}
                            >
                              {
                                market.steamBooks
                              }
                            </p>
                          </div>

                          <div className="rounded-xl border border-white/[0.06] bg-black/10 p-3">
                            <p className="text-[9px] uppercase tracking-wider text-zinc-700">
                              Consensus
                            </p>

                            <p className="mt-2 font-semibold">
                              {market.consensus.toFixed(
                                0
                              )}
                              %
                            </p>
                          </div>

                          <div className="rounded-xl border border-white/[0.06] bg-black/10 p-3">
                            <p className="text-[9px] uppercase tracking-wider text-zinc-700">
                              Snapshots
                            </p>

                            <p className="mt-2 font-semibold">
                              {
                                market.snapshots
                              }
                            </p>
                          </div>
                        </div>

                        <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-white/[0.06] pt-4 text-xs">

                          <span className="text-zinc-600">
                            Supporting{" "}
                            <span className="font-medium text-zinc-300">
                              {
                                market.supportingBooks
                              }
                            </span>
                          </span>

                          <span className="text-zinc-600">
                            Opposing{" "}
                            <span className="font-medium text-zinc-300">
                              {
                                market.opposingBooks
                              }
                            </span>
                          </span>

                          <span className="text-zinc-600">
                            Largest
                            Point Move{" "}
                            <span className="font-medium text-zinc-300">
                              {market.largestPointMove.toFixed(
                                1
                              )}{" "}
                              pts
                            </span>
                          </span>

                          <span className="text-zinc-600">
                            Largest
                            Price Move{" "}
                            <span className="font-medium text-zinc-300">
                              {market.largestPriceMove.toFixed(
                                0
                              )}
                            </span>
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* RIGHT */}

                    <div className="min-w-[300px]">

                      <div className="grid grid-cols-2 gap-3">

                        <div className="rounded-2xl border border-white/[0.07] bg-black/10 p-5">
                          <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                            Confidence
                          </p>

                          <p className="mt-2 text-2xl font-semibold">
                            {
                              opportunity.confidence
                            }
                          </p>
                        </div>

                        <div className="rounded-2xl border border-white/[0.07] bg-black/10 p-5">
                          <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                            Model Edge
                          </p>

                          <p className="mt-2 text-2xl font-semibold text-emerald-400">
                            +
                            {opportunity.edge.toFixed(
                              1
                            )}
                            %
                          </p>
                        </div>

                        <div className="rounded-2xl border border-white/[0.07] bg-black/10 p-5">
                          <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                            Kelly 20%
                          </p>

                          <p className="mt-2 text-xl font-semibold">
                            {(
                              opportunity.kelly20 *
                              100
                            ).toFixed(
                              1
                            )}
                            %
                          </p>
                        </div>

                        <div className="rounded-2xl border border-white/[0.07] bg-black/10 p-5">
                          <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                            Fair Odds
                          </p>

                          <p className="mt-2 text-xl font-semibold">
                            {
                              opportunity.fairOdds
                            }
                          </p>
                        </div>
                      </div>

                      <div className="mt-3 grid gap-3">

                        <Link
                          href={`/opportunities/${opportunity.id}`}
                          className="flex h-11 w-full items-center justify-center rounded-lg border border-white/10 bg-transparent px-5 text-sm font-medium text-white transition hover:bg-white/[0.05]"
                        >
                          View Full
                          Analysis →
                        </Link>

                        <Button
                          onClick={() =>
                            addToCard(
                              opportunity
                            )
                          }
                          disabled={
                            isAdded
                          }
                          className={
                            isAdded
                              ? "h-11 w-full bg-emerald-400/10 text-emerald-300"
                              : "h-11 w-full bg-white text-black hover:bg-zinc-200"
                          }
                        >
                          {isAdded
                            ? snapshotErrors[opportunity.id]
                              ? "Added (tracking failed)"
                              : "Added ✓"
                            : "Add to My Card"}
                        </Button>

                        {isAdded && snapshotErrors[opportunity.id] && (
                          <p className="text-xs text-amber-400">
                            {snapshotErrors[opportunity.id]}
                          </p>
                        )}

                        {isAdded && !(snapshotErrors[opportunity.id]) && (
                          <Link
                            href="/my-card"
                            className="flex h-11 w-full items-center justify-center rounded-lg border border-white/10 bg-transparent px-5 text-sm font-medium text-white transition hover:bg-white/[0.05]"
                          >
                            View My
                            Card →
                          </Link>
                        )}
                      </div>
                    </div>
                  </div>
                </article>
              );
            }
          )}
        </section>

        {/* EMPTY STATE */}

        {filteredOpportunities.length ===
          0 && (
          <section className="mt-8 rounded-3xl border border-white/[0.08] bg-[#0D131C] p-8">

            <h2 className="text-2xl font-semibold">
              No opportunities
              match those filters.
            </h2>

            <p className="mt-3 text-sm text-zinc-500">
              Reset the filters to
              return to the full
              model board.
            </p>

            <Button
              onClick={() => {
                setSortBy("rank");

                setSportsbookFilter(
                  "all"
                );

                setMarketFilter(
                  "all"
                );
              }}
              className="mt-6 bg-white text-black hover:bg-zinc-200"
            >
              Reset Filters
            </Button>
          </section>
        )}
      </div>
    </main>
  );
}