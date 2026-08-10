import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function MyCardPage() {
  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-5xl px-6 py-10">

        <Link
          href="/"
          className="text-sm text-zinc-500 transition hover:text-white"
        >
          ← Home
        </Link>

        <section className="mt-14">
          <p className="text-xs uppercase tracking-[0.2em] text-zinc-600">
            My Card
          </p>

          <h1 className="mt-4 text-5xl font-semibold">
            Review your bets before you act.
          </h1>

          <p className="mt-4 max-w-2xl text-zinc-500">
            Your selected opportunities will live here so you can review
            confidence, exposure, and risk before placing anything.
          </p>
        </section>

        <section className="mt-10 grid gap-4 md:grid-cols-3">
          <div className="rounded-2xl border border-white/10 bg-[#0D131C] p-6">
            <p className="text-xs text-zinc-600">TOTAL EXPOSURE</p>
            <p className="mt-3 text-3xl font-semibold">1.75 Units</p>
          </div>

          <div className="rounded-2xl border border-white/10 bg-[#0D131C] p-6">
            <p className="text-xs text-zinc-600">AVG CONFIDENCE</p>
            <p className="mt-3 text-3xl font-semibold">88.5</p>
          </div>

          <div className="rounded-2xl border border-white/10 bg-[#0D131C] p-6">
            <p className="text-xs text-zinc-600">PORTFOLIO RISK</p>
            <p className="mt-3 text-3xl font-semibold text-emerald-400">
              Moderate
            </p>
          </div>
        </section>

        <section className="mt-8 rounded-3xl border border-white/10 bg-[#0D131C] p-7">
          <p className="text-sm text-zinc-500">Bills @ Ravens</p>

          <h2 className="mt-2 text-3xl font-semibold">
            Buffalo +3
          </h2>

          <div className="mt-6 grid gap-3 md:grid-cols-4">
            <div className="rounded-xl border border-white/10 p-4">
              <p className="text-xs text-zinc-600">CONFIDENCE</p>
              <p className="mt-2 text-xl font-semibold">91</p>
            </div>

            <div className="rounded-xl border border-white/10 p-4">
              <p className="text-xs text-zinc-600">EDGE</p>
              <p className="mt-2 text-xl font-semibold text-emerald-400">
                +6.8%
              </p>
            </div>

            <div className="rounded-xl border border-white/10 p-4">
              <p className="text-xs text-zinc-600">STAKE</p>
              <p className="mt-2 text-xl font-semibold">1.0 Unit</p>
            </div>

            <div className="rounded-xl border border-white/10 p-4">
              <p className="text-xs text-zinc-600">STATUS</p>
              <p className="mt-2 text-xl font-semibold">Ready</p>
            </div>
          </div>
        </section>

        <section className="mt-8 rounded-3xl border border-amber-500/20 bg-amber-500/5 p-7">
          <p className="text-xs uppercase tracking-[0.18em] text-amber-400">
            Final Review
          </p>

          <h2 className="mt-3 text-2xl font-semibold">
            No critical conflicts detected.
          </h2>

          <p className="mt-3 max-w-2xl text-zinc-400">
            We&apos;ll continue monitoring injuries, weather, and market
            movement before kickoff.
          </p>

          <div className="mt-6 flex gap-3">
            <Button className="bg-white text-black hover:bg-zinc-200">
              Continue to Sportsbook →
            </Button>

            <Link href="/opportunities">
              <Button
                variant="outline"
                className="border-white/10 bg-transparent text-white"
              >
                Add More Opportunities
              </Button>
            </Link>
          </div>
        </section>

      </div>
    </main>
  );
}