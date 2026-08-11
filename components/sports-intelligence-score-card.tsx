type SportsIntelligenceScore = {
  score: number;
  grade: string;
  stars: number;
  recommendation: string;
  reasons: string[];
};

export default function SportsIntelligenceScoreCard({
  score,
}: {
  score: SportsIntelligenceScore;
}) {
  const stars = "★".repeat(score.stars);
  const emptyStars = "☆".repeat(5 - score.stars);

  const scoreColor =
    score.score >= 90
      ? "text-emerald-400"
      : score.score >= 80
      ? "text-sky-400"
      : score.score >= 70
      ? "text-amber-400"
      : "text-zinc-400";

  return (
    <div className="rounded-2xl border border-white/[0.08] bg-[#0A1018] p-5">
      <div className="flex flex-wrap items-start justify-between gap-5">
        <div>
          <p className="text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-600">
            Sports Intelligence Score
          </p>

          <div className="mt-3 flex items-end gap-3">
            <span className={`text-4xl font-semibold ${scoreColor}`}>
              {score.score.toFixed(1)}
            </span>

            <span className="pb-1 text-sm text-zinc-600">
              /100
            </span>
          </div>

          <p className="mt-2 text-sm text-zinc-500">
            {score.recommendation}
          </p>
        </div>

        <div className="text-right">
          <p className={`text-3xl font-semibold ${scoreColor}`}>
            {score.grade}
          </p>

          <p className="mt-2 tracking-[0.12em] text-amber-400">
            {stars}
            <span className="text-zinc-700">{emptyStars}</span>
          </p>
        </div>
      </div>

      <div className="mt-5 border-t border-white/[0.06] pt-4">
        <p className="text-[10px] uppercase tracking-[0.16em] text-zinc-700">
          Why
        </p>

        <div className="mt-3 space-y-2">
          {score.reasons.map((reason) => (
            <p
              key={reason}
              className="text-sm leading-6 text-zinc-400"
            >
              <span className="mr-2 text-emerald-400">✓</span>
              {reason}
            </p>
          ))}
        </div>
      </div>
    </div>
  );
}