import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const briefingItems = [
  {
    eyebrow: "INJURY",
    title: "Baltimore LT ruled out",
    summary:
      "This strengthens Buffalo's defensive matchup and slightly improves our Buffalo position.",
    impact: "Buffalo edge +1.8%",
    color: "text-red-400",
  },
  {
    eyebrow: "MARKET",
    title: "Buffalo moved from +2.5 to +3",
    summary:
      "The market has moved, but the current number remains above our fair line.",
    impact: "Value still available",
    color: "text-amber-400",
  },
  {
    eyebrow: "WEATHER",
    title: "Conditions remain neutral",
    summary:
      "Wind and precipitation are not currently significant enough to alter the game projection.",
    impact: "No model adjustment",
    color: "text-sky-400",
  },
];

export default function BriefingPage() {
  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-5xl px-6 py-10 lg:px-10">
        <div className="flex items-center justify-between">
          <Link
            href="/"
            className="text-sm text-zinc-500 transition hover:text-white"
          >
            ← Home
          </Link>

          <Badge
            variant="outline"
            className="border-white/10 bg-white/[0.03] text-zinc-400"
          >
            Updated 2 min ago
          </Badge>
        </div>

        <section className="mt-14">
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-zinc-600">
            Sunday Executive Briefing
          </p>

          <h1 className="mt-4 max-w-3xl text-4xl font-semibold tracking-[-0.03em] md:text-6xl">
            Here&apos;s what changed before you make a decision.
          </h1>

          <p className="mt-5 max-w-2xl text-base leading-7 text-zinc-500">
            We filtered today&apos;s injuries, weather, market movement, model
            updates, and fantasy-impacting news down to the information most
            likely to affect your decisions.
          </p>

          <div className="mt-8 flex flex-wrap gap-6 border-y border-white/[0.07] py-5">
            <div>
              <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                Review time
              </p>
              <p className="mt-1 text-lg font-semibold">4 min</p>
            </div>

            <div>
              <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                Important changes
              </p>
              <p className="mt-1 text-lg font-semibold">3</p>
            </div>

            <div>
              <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                Current confidence
              </p>
              <p className="mt-1 text-lg font-semibold">High</p>
            </div>
          </div>
        </section>

        <section className="mt-10 space-y-4">
          {briefingItems.map((item, index) => (
            <article
              key={item.title}
              className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7 md:p-8"
            >
              <div className="flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
                <div className="max-w-2xl">
                  <div className="flex items-center gap-3">
                    <span className="text-xs text-zinc-700">
                      0{index + 1}
                    </span>
                    <p
                      className={`text-[11px] font-medium tracking-[0.16em] ${item.color}`}
                    >
                      {item.eyebrow}
                    </p>
                  </div>

                  <h2 className="mt-4 text-2xl font-semibold tracking-tight">
                    {item.title}
                  </h2>

                  <p className="mt-3 text-sm leading-7 text-zinc-500">
                    {item.summary}
                  </p>
                </div>

                <div className="min-w-44 rounded-2xl border border-white/[0.07] bg-black/10 p-4">
                  <p className="text-[11px] uppercase tracking-[0.15em] text-zinc-700">
                    Decision impact
                  </p>
                  <p className="mt-2 text-sm font-medium text-zinc-200">
                    {item.impact}
                  </p>
                </div>
              </div>
            </article>
          ))}
        </section>

        <section className="mt-10 rounded-3xl border border-emerald-400/15 bg-emerald-400/[0.04] p-8">
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-400">
            Briefing conclusion
          </p>

          <h2 className="mt-3 text-3xl font-semibold tracking-tight">
            Buffalo +3 remains today&apos;s strongest opportunity.
          </h2>

          <p className="mt-4 max-w-2xl text-sm leading-7 text-zinc-400">
            The injury adjustment improved the matchup, weather remains neutral,
            and the current market price still provides value relative to our
            fair line.
          </p>
 <div className="mt-7 flex flex-wrap gap-3">
  <Link href="/opportunities">
    <Button className="h-11 bg-white px-5 text-black hover:bg-zinc-200">
      Review Opportunity →
    </Button>
  </Link>

  <Link href="/">
    <Button
      variant="outline"
      className="h-11 border-white/10 bg-transparent px-5 text-white hover:bg-white/[0.05]"
    >
      Back Home
    </Button>
  </Link>
</div>
  </section>
      </div>
    </main>
  );
}  