import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const nav = [
  "Today's Briefing",
  "Games",
  "Opportunities",
  "Fantasy",
  "My Card",
  "Performance",
];

export default function Home() {
  return (
    <main className="min-h-screen bg-[#090D14] text-white">
      <div className="flex min-h-screen">

        {/* SIDEBAR */}
        <aside className="hidden w-64 shrink-0 border-r border-white/[0.07] bg-[#0C111A] p-6 lg:block">
          <div className="mb-10">
            <p className="text-lg font-semibold tracking-tight">
              Sports Intelligence
            </p>
            <p className="mt-1 text-xs text-zinc-500">
              NFL Decision Platform
            </p>
          </div>

          <nav className="space-y-1">
            {nav.map((item, index) => (
              <button
                key={item}
                className={`w-full rounded-lg px-3 py-2.5 text-left text-sm transition ${
                  index === 0
                    ? "bg-white/[0.08] font-medium text-white"
                    : "text-zinc-500 hover:bg-white/[0.04] hover:text-zinc-200"
                }`}
              >
                {item}
              </button>
            ))}
          </nav>

          <div className="absolute bottom-8">
            <p className="text-xs text-zinc-600">SPORTS INTELLIGENCE OS</p>
            <p className="mt-1 text-xs text-zinc-700">Private Alpha</p>
          </div>
        </aside>

        {/* MAIN AREA */}
        <section className="flex-1">

          {/* HEADER */}
          <header className="border-b border-white/[0.07]">
            <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-5 lg:px-10">
              <div>
                <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-600">
                  NFL Week 1 • Sunday
                </p>
                <h1 className="mt-1 text-2xl font-semibold tracking-tight">
                  Welcome Back, Nick
                </h1>
              </div>

              <Badge
                variant="outline"
                className="border-emerald-500/20 bg-emerald-500/10 text-emerald-400"
              >
                Sunday Mode
              </Badge>
            </div>
          </header>

          <div className="mx-auto max-w-7xl px-6 py-10 lg:px-10">

            {/* INTRO */}
            <div className="mb-8">
              <p className="text-sm text-zinc-500">YOUR DAY AT A GLANCE</p>

              <div className="mt-2 flex flex-col justify-between gap-4 md:flex-row md:items-end">
                <div>
                  <h2 className="max-w-3xl text-4xl font-semibold tracking-tight md:text-5xl">
                    Your briefing is ready.
                  </h2>
                  <p className="mt-3 max-w-2xl text-base leading-7 text-zinc-400">
                    We reviewed injuries, weather, market movement, model
                    signals, and fantasy-impacting news since your last visit.
                  </p>
                </div>

                <div className="text-left md:text-right">
                  <p className="text-xs uppercase tracking-wider text-zinc-600">
                    Estimated review
                  </p>
                  <p className="mt-1 text-2xl font-semibold">4 min</p>
                </div>
              </div>
            </div>

            {/* MAIN BRIEFING CARD */}
            <Card className="overflow-hidden border-white/[0.08] bg-[#111722] text-white shadow-2xl shadow-black/20">
              <CardHeader className="border-b border-white/[0.07] p-7">
                <div className="flex flex-col justify-between gap-5 md:flex-row md:items-center">
                  <div>
                    <CardDescription className="text-zinc-500">
                      Since your last visit
                    </CardDescription>

                    <CardTitle className="mt-1 text-2xl font-semibold">
                      3 things changed that deserve your attention
                    </CardTitle>
                  </div>

                  <Button className="h-11 bg-white px-6 text-black hover:bg-zinc-200">
                    Start Briefing →
                  </Button>
                </div>
              </CardHeader>

              <CardContent className="grid gap-0 p-0 md:grid-cols-3">

                <div className="border-b border-white/[0.07] p-6 md:border-b-0 md:border-r">
                  <div className="mb-4 flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-red-400" />
                    <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">
                      Injury
                    </p>
                  </div>

                  <p className="text-lg font-medium">1 material update</p>
                  <p className="mt-2 text-sm leading-6 text-zinc-500">
                    One status change affects a game currently on your watchlist.
                  </p>
                </div>

                <div className="border-b border-white/[0.07] p-6 md:border-b-0 md:border-r">
                  <div className="mb-4 flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-amber-400" />
                    <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">
                      Market
                    </p>
                  </div>

                  <p className="text-lg font-medium">2 meaningful moves</p>
                  <p className="mt-2 text-sm leading-6 text-zinc-500">
                    One number may be losing value as kickoff approaches.
                  </p>
                </div>

                <div className="p-6">
                  <div className="mb-4 flex items-center gap-2">
                    <span className="h-2 w-2 rounded-full bg-sky-400" />
                    <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">
                      Weather
                    </p>
                  </div>

                  <p className="text-lg font-medium">1 game to monitor</p>
                  <p className="mt-2 text-sm leading-6 text-zinc-500">
                    Conditions could affect passing and kicking expectations.
                  </p>
                </div>

              </CardContent>
            </Card>

            {/* FOCUS AREA */}
            <div className="mt-8">
              <div className="mb-4 flex items-end justify-between">
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider text-zinc-600">
                    After your briefing
                  </p>
                  <h3 className="mt-1 text-xl font-semibold">
                    Where your attention will go
                  </h3>
                </div>
              </div>

              <div className="grid gap-4 md:grid-cols-3">

                <Card className="border-white/[0.07] bg-[#0F151E] text-white">
                  <CardHeader>
                    <CardDescription className="text-zinc-600">
                      BETTING
                    </CardDescription>
                    <CardTitle className="text-xl">
                      4 opportunities
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm leading-6 text-zinc-500">
                      Two currently meet your highest research threshold.
                    </p>
                  </CardContent>
                </Card>

                <Card className="border-white/[0.07] bg-[#0F151E] text-white">
                  <CardHeader>
                    <CardDescription className="text-zinc-600">
                      FANTASY
                    </CardDescription>
                    <CardTitle className="text-xl">
                      1 decision
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm leading-6 text-zinc-500">
                      One starter requires attention before inactive reports.
                    </p>
                  </CardContent>
                </Card>

                <Card className="border-white/[0.07] bg-[#0F151E] text-white">
                  <CardHeader>
                    <CardDescription className="text-zinc-600">
                      MONITOR
                    </CardDescription>
                    <CardTitle className="text-xl">
                      2 situations
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-sm leading-6 text-zinc-500">
                      We&apos;re waiting for more information before recommending action.
                    </p>
                  </CardContent>
                </Card>

              </div>
            </div>

          </div>
        </section>
      </div>
    </main>
  );
}