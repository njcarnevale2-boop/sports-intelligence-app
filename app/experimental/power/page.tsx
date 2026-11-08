"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { fetchJson } from "@/app/lib/api";
import TeamLogo from "@/components/team-logo";
import {
  buildProjectionGroups, clearMarketData, formatKickoffUtc, marketExpiryAt,
  MARKET_DATA_UNAVAILABLE, nextProjectionUpdateAt, signedSpread, spreadSelections,
} from "./presentation";

type MarketQuote = {
  sportsbookKey: string;
  sportsbookTitle: string;
  providerEventId: string;
  homeSpreadPoint: number;
  awaySpreadPoint: number;
  homePrice: number;
  awayPrice: number;
  quoteTimestamp: string;
};

type PowerResponse = {
  season: number;
  week: number;
  count: number;
  analysisType: "EXPERIMENTAL_POWER_ONLY";
  projectionReadiness: "NOT_ACTIVE";
  artifactId: string;
  modelVersion: string;
  productionEligible: false;
  officialEligible: false;
  games: {
    eventId: string;
    awayTeam: string;
    homeTeam: string;
    kickoffUtc: string;
    awayPower: number;
    homePower: number;
    homeExpectedMargin: number;
    homeFairSpread: number;
    marketStatus: "AVAILABLE" | "MARKET_DATA_UNAVAILABLE" | "ALREADY_STARTED";
    marketQuotes: MarketQuote[];
  }[];
  probabilitiesComputed: false;
  evComputed: false;
  personnelApproval: "NOT_EVALUATED";
  marketDataStatus: "AVAILABLE" | "MARKET_DATA_UNAVAILABLE";
  marketDataReason: string | null;
  marketDataCapturedAt: string | null;
};

function signedOdds(value: number) {
  return `${value > 0 ? "+" : ""}${Math.round(value)}`;
}

export default function ExperimentalPowerPage() {
  const [data, setData] = useState<PowerResponse | null>(null);
  const [error, setError] = useState("");
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    const tick = () => setNow(Date.now());
    tick();
    document.addEventListener("visibilitychange", tick);
    return () => document.removeEventListener("visibilitychange", tick);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let inFlight = false;
    async function load() {
      if (inFlight) return;
      inFlight = true;
      try {
        const payload = await fetchJson<PowerResponse>(
          "/api/experimental/power-market-comparison?season=2026&week=9",
          { cache: "no-store" },
          30000
        );
        if (
          payload.analysisType !== "EXPERIMENTAL_POWER_ONLY" ||
          payload.projectionReadiness !== "NOT_ACTIVE" ||
          payload.productionEligible !== false ||
          payload.officialEligible !== false ||
          payload.probabilitiesComputed !== false ||
          payload.evComputed !== false ||
          payload.personnelApproval !== "NOT_EVALUATED" ||
          !["AVAILABLE", "MARKET_DATA_UNAVAILABLE"].includes(payload.marketDataStatus) ||
          payload.count !== payload.games.length
        ) {
          throw new Error("Unexpected experimental analysis contract");
        }
        buildProjectionGroups(payload.games, Date.now());
        if (!cancelled) {
          setData(payload);
          setNow(Date.now());
          setError("");
        }
      } catch {
        if (!cancelled) {
          setData((previous) => previous ? clearMarketData(previous) : null);
          setNow(Date.now());
          setError("Experimental power analysis is unavailable.");
        }
      } finally {
        inFlight = false;
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), 30000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    if (!data || now === null) return;
    const deadline = nextProjectionUpdateAt(data.games, data.marketDataCapturedAt, now);
    if (deadline === null) return;
    const delay = Math.min(Math.max(0, deadline - Date.now()), 2147483647);
    const timer = window.setTimeout(() => setNow(Date.now()), delay);
    return () => window.clearTimeout(timer);
  }, [data, now]);

  const groups = data && now !== null ? buildProjectionGroups(data.games, now) : null;
  const marketExpiry = data ? marketExpiryAt(data.games, data.marketDataCapturedAt) : null;
  const hasMarketQuotes = data !== null && now !== null && data.marketDataStatus === "AVAILABLE" &&
    data.games.some((game) => spreadSelections(game, data.marketDataCapturedAt, marketExpiry, now).selections.length > 0);

  function renderGames(games: NonNullable<typeof groups>["upcoming"], started: boolean) {
    if (games.length === 0) {
      return <p className="py-5 text-sm text-zinc-500">No {started ? "started" : "upcoming"} games.</p>;
    }

    return (
      <div className="overflow-x-auto">
        <table className="w-full min-w-[980px] table-fixed text-left text-sm">
          <thead className="text-xs text-zinc-500">
            <tr className="border-b border-white/10">
              <th scope="col" className="w-[22%] py-3 font-medium">Matchup</th>
              <th scope="col" className="w-[14%] py-3 font-medium">Kickoff (UTC)</th>
              <th scope="col" className="w-[13%] py-3 font-medium">Projected winner</th>
              <th scope="col" className="w-[12%] py-3 text-right font-medium">Home margin</th>
              <th scope="col" className="w-[18%] py-3 text-right font-medium">SIA fair spread</th>
              <th scope="col" className="w-[13%] py-3 font-medium">Sportsbook spread</th>
              <th scope="col" className="w-[8%] py-3 font-medium">Quote time</th>
            </tr>
          </thead>
          <tbody>
            {games.map((game) => {
              const source = data?.games.find((item) => item.eventId === game.eventId);
              const market = data && source && now !== null && data.marketDataStatus === "AVAILABLE"
                ? spreadSelections(source, data.marketDataCapturedAt, marketExpiry, now)
                : null;
              const selections = started ? [] : market?.selections ?? [];
              return (
              <tr key={game.eventId} className="border-b border-white/[0.06]">
                <th scope="row" className="py-4 font-medium">
                  <span className="flex flex-wrap items-center gap-1.5 sm:gap-2">
                    <TeamLogo src={`https://a.espncdn.com/i/teamlogos/nfl/500/${game.awayTeam.toLowerCase()}.png`} alt={game.awayTeam} size={22} />
                    {game.awayTeam} <span className="text-zinc-600">@</span> {game.homeTeam}
                    <TeamLogo src={`https://a.espncdn.com/i/teamlogos/nfl/500/${game.homeTeam.toLowerCase()}.png`} alt={game.homeTeam} size={22} />
                    {started && <span className="basis-full text-xs text-amber-300">NOT PREGAME · historical projection</span>}
                  </span>
                </th>
                <td className="py-4 text-zinc-400">{formatKickoffUtc(game.kickoffUtc)}</td>
                <td className="py-4">{game.projectedWinner}</td>
                <td className="py-4 text-right tabular-nums">{signedSpread(game.homeExpectedMargin)} pts</td>
                <td className="py-4 text-right tabular-nums">
                  <span className="block">{game.homeTeam} {signedSpread(game.homeFairSpread)}</span>
                  <span className="block text-xs text-zinc-500">{game.awayTeam} {signedSpread(game.awayFairSpread)}</span>
                </td>
                <td className="py-4 text-amber-100">
                  {selections.length > 0 ? selections.map(({ quote, side, team, sportsbookSpread, fairSpread, pointDifference, price }) => (
                    <span key={`${quote.sportsbookKey}-${quote.providerEventId}`} className="mb-2 block">
                      <span className="font-medium">{quote.sportsbookTitle}</span>: {game.homeTeam} {signedSpread(quote.homeSpreadPoint)} ({signedOdds(quote.homePrice)})
                      <span className="block">{game.awayTeam} {signedSpread(quote.awaySpreadPoint)} ({signedOdds(quote.awayPrice)})</span>
                      <span className="block text-xs text-emerald-300">
                        {side === "TIE" ? "No difference" : `Model-favored: ${team} ${signedSpread(sportsbookSpread)} (${signedOdds(price)})`}
                      </span>
                      <span className="block text-xs text-zinc-500">{side === "TIE" ? game.homeTeam : team} fair {signedSpread(fairSpread)} · difference {signedSpread(pointDifference)} pts</span>
                    </span>
                  )) : started ? `NOT PREGAME · ${MARKET_DATA_UNAVAILABLE}` : MARKET_DATA_UNAVAILABLE}
                </td>
                <td className="py-4 text-zinc-500">
                  {selections.length > 0 ? selections.map(({ quote }) => (
                    <span key={`${quote.sportsbookKey}-${quote.providerEventId}-time`} className="mb-1 block text-xs">
                      {quote.quoteTimestamp}
                    </span>
                  )) : "Unavailable"}
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
        <Link href="/games" className="mb-6 inline-flex items-center gap-2 text-sm text-zinc-400 hover:text-white">
          <ArrowLeft size={16} aria-hidden="true" /> Games
        </Link>
        <header className="border-b border-white/10 pb-5">
          <p className="text-xs uppercase text-amber-300">Experimental · Power Only</p>
          <h1 className="mt-2 text-2xl font-semibold">Week 9 Spread Analysis</h1>
          <p role="status" className="mt-3 text-sm text-amber-200">
            EXPERIMENTAL / UNVALIDATED — NOT OFFICIAL PICKS. Not validated for betting. Personnel not evaluated. Probabilities and EV not computed.
          </p>
          <p role="status" className="mt-3 border-l-2 border-amber-400 pl-3 text-sm text-amber-100">
            {hasMarketQuotes
              ? `Validated staging capture · observed ${data.marketDataCapturedAt ?? "timestamp unavailable"}. No probabilities, EV, or recommendations.`
              : `${MARKET_DATA_UNAVAILABLE}: ${data?.marketDataReason ?? "no validated real sportsbook capture is connected"}. Synthetic and historical lines are not shown.`}
          </p>
          {data && <p className="mt-3 break-all text-xs text-zinc-500">{data.season} · {groups?.upcoming.length ?? 0} pregame · {groups?.started.length ?? 0} started · {data.modelVersion} · {data.artifactId}</p>}
        </header>
        {error && !data ? <p role="alert" className="py-8 text-sm text-rose-300">{error}</p> : !data ? (
          <p className="py-8 text-sm text-zinc-500">Loading experimental power analysis...</p>
        ) : !groups ? <p className="py-8 text-sm text-zinc-500">Checking kickoff times...</p> : (
          <>
            <section aria-labelledby="upcoming-heading" className="mt-6">
              <h2 id="upcoming-heading" className="mb-2 text-sm font-medium text-emerald-300">Pregame projections · {groups.upcoming.length}</h2>
              {renderGames(groups.upcoming, false)}
            </section>
            <section aria-labelledby="started-heading" className="mt-8">
              <h2 id="started-heading" className="mb-2 text-sm font-medium text-amber-300">Already started · historical projections · {groups.started.length}</h2>
              {renderGames(groups.started, true)}
            </section>
          </>
        )}
      </div>
    </main>
  );
}