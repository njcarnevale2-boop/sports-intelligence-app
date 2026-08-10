"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";

type Bet = {
  matchup: string;
  pick: string;
  book: string;
  confidence: number;
  edge: string;
};

export default function MyCardPage() {
  const [bets, setBets] = useState<Bet[]>([]);

  useEffect(() => {
    const saved = localStorage.getItem("sports-intelligence-card");

    if (saved) {
      setBets(JSON.parse(saved));
    }
  }, []);

  function removeBet(pick: string) {
    const updatedBets = bets.filter((bet) => bet.pick !== pick);

    setBets(updatedBets);

    localStorage.setItem(
      "sports-intelligence-card",
      JSON.stringify(updatedBets)
    );
  }

  function clearCard() {
    setBets([]);
    localStorage.removeItem("sports-intelligence-card");
  }

  const averageConfidence =
    bets.length > 0
      ? Math.round(
          bets.reduce((total, bet) => total + bet.confidence, 0) / bets.length
        )
      : 0;

  const averageEdge =
    bets.length > 0
      ? (
          bets.reduce(
            (total, bet) =>
              total + Number.parseFloat(bet.edge.replace("%", "")),
            0
          ) / bets.length
        ).toFixed(1)
      : "0.0";

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-5xl px-6 py-10">
        <section>
          <p className="text-xs uppercase tracking-[0.2em] text-zinc-600">
            My Card
          </p>

          <div className="mt-4 flex flex-col justify-between gap-5 md:flex-row md:items-end">
            <div>
              <h1 className="text-4xl font-semibold tracking-tight md:text-5xl">
                Review your decisions.
              </h1>

              <p className="mt-4 max-w-2xl leading-7 text-zinc-500">
                Review your selected opportunities, portfolio exposure, and
                confidence before making a decision.
              </p>
            </div>

            {bets.length > 0 && (
              <button
                onClick={clearCard}
                className="text-sm text-zinc-600 transition hover:text-red-400"
              >
                Clear Card
              </button>
            )}
          </div>
        </section>

        {bets.length === 0 ? (
          <section className="mt-10 rounded-3xl border border-white/[0.08] bg-[#0D131C] p-10">
            <p className="text-xs uppercase tracking-[0.18em] text-zinc-700">
              No selections
            </p>

            <h2 className="mt-3 text-3xl font-semibold">
              Your card is empty.
            </h2>

            <p className="mt-3 max-w-xl leading-7 text-zinc-500">
              Add opportunities to your card and they&apos;ll appear here for a
              final decision review.
            </p>

            <Link href="/opportunities">
              <Button className="mt-7 bg-white text-black hover:bg-zinc-200">
                Browse Opportunities →
              </Button>
            </Link>
          </section>
        ) : (
          <>
            <section className="mt-10 grid gap-4 md:grid-cols-3">
              <div className="rounded-2xl border border-white/[0.08] bg-[#0D131C] p-6">
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Selections
                </p>

                <p className="mt-3 text-3xl font-semibold">{bets.length}</p>
              </div>

              <div className="rounded-2xl border border-white/[0.08] bg-[#0D131C] p-6">
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Avg Confidence
                </p>

                <p className="mt-3 text-3xl font-semibold">
                  {averageConfidence}
                </p>
              </div>

              <div className="rounded-2xl border border-white/[0.08] bg-[#0D131C] p-6">
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Avg Model Edge
                </p>

                <p className="mt-3 text-3xl font-semibold text-emerald-400">
                  +{averageEdge}%
                </p>
              </div>
            </section>

            <section className="mt-8 space-y-4">
              {bets.map((bet, index) => (
                <article
                  key={`${bet.matchup}-${bet.pick}`}
                  className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7"
                >
                  <div className="flex flex-col gap-7 md:flex-row md:items-center md:justify-between">
                    <div>
                      <div className="flex items-center gap-3">
                        <span className="text-xs text-zinc-700">
                          0{index + 1}
                        </span>

                        <p className="text-sm text-zinc-500">{bet.matchup}</p>
                      </div>

                      <h2 className="mt-3 text-3xl font-semibold">
                        {bet.pick}
                      </h2>

                      <p className="mt-2 text-sm text-zinc-600">
                        Best available at {bet.book}
                      </p>
                    </div>

                    <div className="flex flex-col gap-3 sm:flex-row">
                      <div className="min-w-32 rounded-xl border border-white/[0.07] bg-black/10 p-4">
                        <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                          Confidence
                        </p>

                        <p className="mt-2 text-lg font-semibold">
                          {bet.confidence}
                        </p>
                      </div>

                      <div className="min-w-32 rounded-xl border border-white/[0.07] bg-black/10 p-4">
                        <p className="text-[10px] uppercase tracking-wider text-zinc-700">
                          Edge
                        </p>

                        <p className="mt-2 text-lg font-semibold text-emerald-400">
                          {bet.edge}
                        </p>
                      </div>

                      <button
                        onClick={() => removeBet(bet.pick)}
                        className="rounded-xl border border-white/[0.07] px-5 py-3 text-sm text-zinc-600 transition hover:border-red-400/20 hover:bg-red-400/[0.04] hover:text-red-400"
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                </article>
              ))}
            </section>

            <section className="mt-8 rounded-3xl border border-emerald-400/15 bg-emerald-400/[0.035] p-8">
              <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-400">
                Portfolio Review
              </p>

              <h2 className="mt-3 text-2xl font-semibold">
                Your card is ready for final review.
              </h2>

              <p className="mt-3 max-w-2xl leading-7 text-zinc-500">
                The Intelligence Engine will continue monitoring your selections
                for injuries, weather changes, and meaningful market movement
                before kickoff.
              </p>

              <div className="mt-7 flex flex-wrap gap-3">
                <Button className="bg-white text-black hover:bg-zinc-200">
                  Finalize Card →
                </Button>

                <Link href="/opportunities">
                  <Button
                    variant="outline"
                    className="border-white/10 bg-transparent text-white hover:bg-white/[0.05]"
                  >
                    Add More Opportunities
                  </Button>
                </Link>
              </div>
            </section>
          </>
        )}
      </div>
    </main>
  );
}