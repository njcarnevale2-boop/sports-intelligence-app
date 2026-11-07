"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { fetchJson } from "@/app/lib/api";
import TeamLogo from "@/components/team-logo";

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
    homeFairSpread: number;
  }[];
};

function signed(value: number) {
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

export default function ExperimentalPowerPage() {
  const [data, setData] = useState<PowerResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const payload = await fetchJson<PowerResponse>(
          "/api/experimental/power-projections?season=2026&week=9",
          undefined,
          30000
        );
        if (payload.analysisType !== "EXPERIMENTAL_POWER_ONLY" || payload.projectionReadiness !== "NOT_ACTIVE" || payload.productionEligible !== false || payload.officialEligible !== false || payload.count !== payload.games.length) {
          throw new Error("Unexpected experimental analysis contract");
        }
        if (!cancelled) setData(payload);
      } catch {
        if (!cancelled) setError("Experimental power analysis is unavailable.");
      }
    }
    void load();
    return () => { cancelled = true; };
  }, []);

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
        <Link href="/games" className="mb-6 inline-flex items-center gap-2 text-sm text-zinc-400 hover:text-white">
          <ArrowLeft size={16} aria-hidden="true" /> Games
        </Link>
        <header className="border-b border-white/10 pb-5">
          <p className="text-xs uppercase text-amber-300">Experimental · Power Only</p>
          <h1 className="mt-2 text-2xl font-semibold">Week 9 Power Analysis</h1>
          <p role="status" className="mt-3 text-sm text-amber-200">
            Not approved for betting or Official publication. Personnel not evaluated. Probabilities and EV not computed.
          </p>
          {data && <p className="mt-3 break-all text-xs text-zinc-500">{data.season} · {data.count} games · {data.modelVersion} · {data.artifactId}</p>}
        </header>
        {error ? <p role="alert" className="py-8 text-sm text-rose-300">{error}</p> : !data ? (
          <p className="py-8 text-sm text-zinc-500">Loading experimental power analysis...</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[380px] table-fixed text-left text-sm">
              <thead className="text-xs text-zinc-500">
                <tr className="border-b border-white/10">
                  <th scope="col" className="w-[40%] py-4 font-medium">Matchup</th>
                  <th scope="col" className="py-4 text-right font-medium">Away Power</th>
                  <th scope="col" className="py-4 text-right font-medium">Home Power</th>
                  <th scope="col" className="py-4 text-right font-medium">Home Fair Spread</th>
                </tr>
              </thead>
              <tbody>
                {data.games.map(game => (
                  <tr key={game.eventId} className="border-b border-white/[0.06]">
                    <th scope="row" className="py-4 font-medium">
                      <span className="flex flex-wrap items-center gap-1.5 sm:gap-2">
                        <TeamLogo src={`https://a.espncdn.com/i/teamlogos/nfl/500/${game.awayTeam.toLowerCase()}.png`} alt={game.awayTeam} size={22} />
                        {game.awayTeam} <span className="text-zinc-600">@</span> {game.homeTeam}
                        <TeamLogo src={`https://a.espncdn.com/i/teamlogos/nfl/500/${game.homeTeam.toLowerCase()}.png`} alt={game.homeTeam} size={22} />
                      </span>
                    </th>
                    <td className="text-right tabular-nums text-zinc-400">{signed(game.awayPower)}</td>
                    <td className="text-right tabular-nums text-zinc-400">{signed(game.homePower)}</td>
                    <td className="text-right tabular-nums">{signed(game.homeFairSpread)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}