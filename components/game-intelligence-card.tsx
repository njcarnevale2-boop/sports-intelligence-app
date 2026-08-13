"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import TeamLogo from "@/components/team-logo";

type GameCardData = {
  id?: string;
  eventId?: string;
  matchup?: string;
  awayTeam?: string;
  homeTeam?: string;
  awayLogo?: string;
  homeLogo?: string;
  commenceTime?: string;
  kickoff?: string;
  date?: string;
  sportsIntelligenceScore?: number;
  marketGrade?: string;
  recommendation?: string;
  confidence?: number;
  bestBet?: string;
  bestAvailableLine?: string;
  expectedValue?: string;
  weatherSummary?: string;
  injurySummary?: string;
  topReasons?: string[];
  marketSpread?: number;
  marketTotal?: number;
  projectedAwayScore?: number;
  projectedHomeScore?: number;
  edge?: number;
  evPerDollar?: number;
  book?: string;
  market?: string;
  pick?: string;
  score?: number;
  grade?: string;
  reason?: string;
};

type GameIntelligenceCardProps = {
  game: GameCardData;
  compact?: boolean;
  expanded?: boolean;
  clickable?: boolean;
  highlightElite?: boolean;
  href?: string;
  onAddToCard?: () => void;
};

function scoreTone(score?: number) {
  if ((score ?? 0) >= 85) return "text-emerald-400";
  if ((score ?? 0) >= 75) return "text-sky-400";
  return "text-amber-400";
}

function recommendationBadge(grade?: string) {
  if (grade === "Elite Opportunity") return "border-emerald-400/20 bg-emerald-400/[0.06] text-emerald-300";
  if (grade === "Lean") return "border-sky-400/20 bg-sky-400/[0.06] text-sky-300";
  return "border-amber-400/20 bg-amber-400/[0.06] text-amber-300";
}

export default function GameIntelligenceCard({
  game,
  compact = false,
  expanded = false,
  clickable = true,
  highlightElite = false,
  href,
  onAddToCard,
}: GameIntelligenceCardProps) {
  const card = (
    <article className={`rounded-[28px] border border-white/10 bg-[#0B1119] p-6 shadow-2xl shadow-black/20 ${highlightElite ? "ring-1 ring-emerald-400/20" : ""}`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-[10px] uppercase tracking-[0.26em] text-zinc-600">{game.date ?? game.commenceTime ?? "Matchup"}</p>
          <p className="mt-2 text-sm text-zinc-400">{game.kickoff ?? game.commenceTime ?? "Kickoff TBD"}</p>
        </div>
        <Badge variant="outline" className={recommendationBadge(game.marketGrade ?? game.grade)}>
          {game.marketGrade ?? game.grade ?? game.recommendation ?? "Watch"}
        </Badge>
      </div>

      <div className="mt-6 flex items-center justify-between gap-4">
        <div className="flex flex-1 items-center gap-3">
          <TeamLogo src={game.awayLogo} alt={game.awayTeam ?? "Away"} size={56} />
          <div>
            <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-500">Away</p>
            <p className="text-lg font-semibold">{game.awayTeam ?? "Away"}</p>
          </div>
        </div>

        <div className="px-3 text-center text-sm font-medium text-zinc-500">@</div>

        <div className="flex flex-1 items-center justify-end gap-3">
          <div className="text-right">
            <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-500">Home</p>
            <p className="text-lg font-semibold">{game.homeTeam ?? "Home"}</p>
          </div>
          <TeamLogo src={game.homeLogo} alt={game.homeTeam ?? "Home"} size={56} />
        </div>
      </div>

      <div className="mt-6 grid gap-3 md:grid-cols-3">
        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
          <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">SI Score</p>
          <p className={`mt-2 text-xl font-semibold ${scoreTone(game.sportsIntelligenceScore ?? game.score)}`}>{game.sportsIntelligenceScore ?? game.score ?? "—"}</p>
        </div>
        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
          <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">Recommendation</p>
          <p className="mt-2 text-lg font-semibold text-white">{game.recommendation ?? game.bestBet ?? game.reason ?? "No edge"}</p>
        </div>
        <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
          <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">Confidence</p>
          <p className="mt-2 text-xl font-semibold text-white">{game.confidence ?? "—"}%</p>
        </div>
      </div>

      {!compact && (
        <div className="mt-6 rounded-[24px] border border-white/10 bg-black/20 p-5">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">Best available line</p>
              <p className="mt-2 text-lg font-semibold text-white">{game.bestAvailableLine ?? `${game.marketSpread ?? "—"} / ${game.marketTotal ?? "—"}`}</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">Expected value</p>
              <p className="mt-2 text-lg font-semibold text-emerald-400">{game.expectedValue ?? `${game.evPerDollar ? `+$${game.evPerDollar.toFixed(2)}` : "—"}`}</p>
            </div>
          </div>

          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 text-sm leading-7 text-zinc-400">
              <p><span className="font-medium text-zinc-200">Weather:</span> {game.weatherSummary ?? "Neutral conditions."}</p>
              <p className="mt-2"><span className="font-medium text-zinc-200">Injury:</span> {game.injurySummary ?? "No meaningful edge."}</p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
              <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">Top reasons</p>
              <ul className="mt-2 space-y-2 text-sm text-zinc-400">
                {(game.topReasons ?? [game.reason ?? "High model conviction", game.bestBet ?? "Strong market signal", game.marketGrade ?? "Balanced context"]).slice(0, 3).map((reason) => (
                  <li key={reason} className="flex gap-2"><span className="text-emerald-400">•</span><span>{reason}</span></li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      <div className="mt-6 flex flex-wrap gap-3">
        {href ? (
          <Link href={href} className="rounded-full border border-white/10 px-4 py-2 text-sm text-zinc-300 transition hover:border-white/20 hover:text-white">
            View Intelligence
          </Link>
        ) : null}
        {onAddToCard ? (
          <Button variant="outline" className="border-white/10 bg-transparent px-4 py-2 text-sm text-zinc-300 hover:bg-white/[0.05]" onClick={onAddToCard}>
            Add To My Card
          </Button>
        ) : null}
        {game.market ? (
          <Link href="/line-movement" className="rounded-full border border-white/10 px-4 py-2 text-sm text-zinc-300 transition hover:border-white/20 hover:text-white">
            View Market
          </Link>
        ) : null}
      </div>
    </article>
  );

  return card;
}
