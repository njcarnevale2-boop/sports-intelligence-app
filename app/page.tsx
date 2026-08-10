import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import AddToCardButton from "@/components/add-to-card-button";

const alerts = [
  {
    label: "INJURY",
    title: "Baltimore LT ruled out",
    detail: "Buffalo's matchup improved after the update.",
    color: "text-red-400",
  },
  {
    label: "MARKET",
    title: "Buffalo moved from +2.5 to +3",
    detail: "Value remains, but the number is beginning to move.",
    color: "text-amber-400",
  },
  {
    label: "WEATHER",
    title: "Conditions remain neutral",
    detail: "No meaningful weather adjustment is needed right now.",
    color: "text-sky-400",
  },
];

export default function Home() {
  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <header className="border-b border-white/[0.06]">
        <div className="mx-auto flex max-w-[1320px] items-center justify-between px-6 py-5 lg:px-10">
          <div>
            <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-zinc-600">
              NFL Week 1 • Sunday
            </p>

            <h1 className="mt-1 text-xl font-semibold tracking-tight">
              Welcome back, Nick
            </h1>
          </div>

          <Badge
            variant="outline"
            className="border-white/10 bg-white/[0.03] text-zinc-400"
          >
            Sunday Mode
          </Badge>
        </div>
      </header>

      <div className="mx-auto max-w-[1320px] px-6 py-10 lg:px-10">
        <section>
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-zinc-600">
            Your day at a glance
          </p>

          <div className="mt-3 flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h2 className="max-w-3xl text-4xl font-semibold tracking-[-0.03em] md:text-5xl">
                Three things deserve your attention today.
              </h2>

              <p className="mt-4 max-w-2xl text-base leading-7 text-zinc-500">
                We reviewed injuries, weather, market movement, model output,
                and fantasy-impacting news since your last visit.
              </p>

              <Link href="/briefing">
                <Button className="mt-6 h-11 bg-white px-5 text-black hover:bg-zinc-200">
                  Start Briefing →
                </Button>
              </Link>
            </div>

            <div className="flex gap-8">
              <div>
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Review time
                </p>
                <p className="mt-1 text-xl font-semibold">4 min</p>
              </div>

              <div>
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Games today
                </p>
                <p className="mt-1 text-xl font-semibold">13</p>
              </div>
            </div>
          </div>
        </section>

        <section className="mt-10 overflow-hidden rounded-3xl border border-white/[0.08] bg-[linear-gradient(135deg,#121823_0%,#0D121A_100%)] shadow-2xl shadow-black/30">
          <div className="grid lg:grid-cols-[1.3fr_0.7fr]">
            <div className="p-8 lg:p-10">
              <div className="flex items-center gap-3">
                <Badge className="bg-emerald-400 text-black hover:bg-emerald-400">
                  Top Opportunity
                </Badge>

                <span className="text-xs text-zinc-600">
                  Highest-rated opportunity on today&apos;s slate
                </span>
              </div>

              <p className="mt-8 text-sm text-zinc-500">
                Bills @ Ravens
              </p>

              <div className="mt-2 flex flex-wrap items-end gap-x-5 gap-y-2">
                <h3 className="text-4xl font-semibold tracking-tight">
                  Buffalo +3
                </h3>

                <span className="pb-1 text-sm text-zinc-500">
                  FanDuel
                </span>
              </div>

              <p className="mt-4 max-w-2xl text-base leading-7 text-zinc-400">
                The current number remains above our fair line after the latest
                injury adjustment. Market movement has narrowed the edge, but
                meaningful value still remains.
              </p>

              <div className="mt-8 flex flex-wrap gap-3">
                <Link href="/briefing">
                  <Button className="h-11 bg-white px-5 text-black hover:bg-zinc-200">
                    View Analysis →
                  </Button>
                </Link>
<AddToCardButton />    
              </div>
            </div>

            <div className="border-t border-white/[0.07] bg-black/10 p-8 lg:border-l lg:border-t-0 lg:p-10">
              <p className="text-xs uppercase tracking-[0.18em] text-zinc-600">
                Decision Snapshot
              </p>

              <div className="mt-7 space-y-6">
                <div className="flex items-end justify-between border-b border-white/[0.07] pb-5">
                  <span className="text-sm text-zinc-500">Confidence</span>
                  <span className="text-2xl font-semibold">91</span>
                </div>

                <div className="flex items-end justify-between border-b border-white/[0.07] pb-5">
                  <span className="text-sm text-zinc-500">Model Edge</span>
                  <span className="text-2xl font-semibold text-emerald-400">
                    +6.8%
                  </span>
                </div>

                <div className="flex items-end justify-between">
                  <span className="text-sm text-zinc-500">Market Status</span>
                  <span className="text-sm font-medium text-zinc-200">
                    Best number still available
                  </span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="mt-8">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-700">
              What changed
            </p>

            <h3 className="mt-1 text-xl font-semibold">
              Intelligence that may affect your decisions
            </h3>
          </div>

          <div className="mt-5 grid gap-4 lg:grid-cols-3">
            {alerts.map((alert) => (
              <article
                key={alert.title}
                className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6"
              >
                <p
                  className={`text-[11px] font-medium tracking-[0.16em] ${alert.color}`}
                >
                  {alert.label}
                </p>

                <h4 className="mt-4 text-lg font-medium">
                  {alert.title}
                </h4>

                <p className="mt-2 text-sm leading-6 text-zinc-500">
                  {alert.detail}
                </p>
              </article>
            ))}
          </div>
        </section>

        <section className="mt-8 grid gap-4 lg:grid-cols-3">
          <Link
            href="/opportunities"
            className="rounded-2xl border border-white/[0.07] bg-[#0B1119] p-6 transition hover:border-white/15"
          >
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Betting
            </p>
            <p className="mt-3 text-2xl font-semibold">4 opportunities</p>
            <p className="mt-2 text-sm text-zinc-500">
              Two currently clear your strongest threshold.
            </p>
          </Link>

          <article className="rounded-2xl border border-white/[0.07] bg-[#0B1119] p-6">
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Fantasy
            </p>
            <p className="mt-3 text-2xl font-semibold">1 lineup decision</p>
            <p className="mt-2 text-sm text-zinc-500">
              One starter needs attention before inactive reports.
            </p>
          </article>

          <Link
            href="/my-card"
            className="rounded-2xl border border-white/[0.07] bg-[#0B1119] p-6 transition hover:border-white/15"
          >
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              My Card
            </p>
            <p className="mt-3 text-2xl font-semibold">2 selections</p>
            <p className="mt-2 text-sm text-zinc-500">
              Review exposure and risk before placing anything.
            </p>
          </Link>
        </section>
      </div>
    </main>
  );
}