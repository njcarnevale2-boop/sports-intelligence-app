"use client";

import { useState } from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  opportunities,
  type Opportunity,
} from "@/data/opportunities";

export default function OpportunitiesPage() {
  const [added, setAdded] = useState<string[]>([]);

  function addToCard(opportunity: Opportunity) {
    const existing = localStorage.getItem("sports-intelligence-card");

    const currentCard: Opportunity[] = existing
      ? JSON.parse(existing)
      : [];

    const alreadyExists = currentCard.some(
      (bet) => bet.id === opportunity.id
    );

    if (!alreadyExists) {
      localStorage.setItem(
        "sports-intelligence-card",
        JSON.stringify([...currentCard, opportunity])
      );
    }

    setAdded((current) =>
      current.includes(opportunity.id)
        ? current
        : [...current, opportunity.id]
    );
  }

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-6xl px-6 py-10 lg:px-10">
        <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.2em] text-zinc-600">
              Opportunity Intelligence
            </p>

            <h1 className="mt-3 text-4xl font-semibold tracking-[-0.03em] md:text-6xl">
              Today&apos;s best opportunities.
            </h1>

            <p className="mt-5 max-w-2xl text-base leading-7 text-zinc-500">
              Opportunities are ranked using model edge, confidence, injuries,
              market movement, weather, and decision risk.
            </p>
          </div>

          <Link href="/my-card">
            <Button
              variant="outline"
              className="border-white/10 bg-transparent text-white hover:bg-white/[0.05]"
            >
              View My Card →
            </Button>
          </Link>
        </div>

        <div className="mt-10 flex flex-wrap items-center gap-8 border-y border-white/[0.07] py-5">
          <div>
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Opportunities
            </p>
            <p className="mt-1 text-xl font-semibold">
              {opportunities.length}
            </p>
          </div>

          <div>
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Strongest Edge
            </p>
            <p className="mt-1 text-xl font-semibold text-emerald-400">
              {opportunities[0]?.edge ?? "—"}
            </p>
          </div>

          <div>
            <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
              Highest Confidence
            </p>
            <p className="mt-1 text-xl font-semibold">
              {Math.max(...opportunities.map((item) => item.confidence))}
            </p>
          </div>
        </div>

        <section className="mt-8 space-y-5">
          {opportunities.map((opportunity, index) => {
            const isAdded = added.includes(opportunity.id);

            return (
              <article
                key={opportunity.id}
                className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7 md:p-8"
              >
                <div className="flex flex-col gap-8 lg:flex-row lg:items-center lg:justify-between">
                  <div className="max-w-2xl">
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-zinc-700">
                        0{index + 1}
                      </span>

                      <Badge
                        variant="outline"
                        className="border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-400"
                      >
                        {opportunity.status}
                      </Badge>
                    </div>

                    <p className="mt-5 text-sm text-zinc-500">
                      {opportunity.matchup}
                    </p>

                    <h2 className="mt-1 text-3xl font-semibold tracking-tight">
                      {opportunity.pick}
                    </h2>

                    <p className="mt-1 text-sm text-zinc-600">
                      Best available at {opportunity.book}
                    </p>

                    <p className="mt-5 text-sm leading-7 text-zinc-500">
                      {opportunity.reason}
                    </p>
                  </div>

                  <div className="min-w-[300px]">
                    <div className="grid grid-cols-2 gap-3">
                      <div className="rounded-2xl border border-white/[0.07] bg-black/10 p-5">
                        <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                          Confidence
                        </p>

                        <p className="mt-2 text-2xl font-semibold">
                          {opportunity.confidence}
                        </p>
                      </div>

                      <div className="rounded-2xl border border-white/[0.07] bg-black/10 p-5">
                        <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                          Model Edge
                        </p>

                        <p className="mt-2 text-2xl font-semibold text-emerald-400">
                          {opportunity.edge}
                        </p>
                      </div>
                    </div>

                    <div className="mt-3 grid gap-3">
                      <Link href={`/opportunities/${opportunity.id}`}>
                        <Button
                          variant="outline"
                          className="h-11 w-full border-white/10 bg-transparent text-white hover:bg-white/[0.05]"
                        >
                          View Full Analysis →
                        </Button>
                      </Link>

                      <Button
                        onClick={() => addToCard(opportunity)}
                        disabled={isAdded}
                        className={
                          isAdded
                            ? "h-11 bg-emerald-400/10 text-emerald-300"
                            : "h-11 bg-white text-black hover:bg-zinc-200"
                        }
                      >
                        {isAdded ? "Added ✓" : "Add to My Card"}
                      </Button>

                      {isAdded && (
                        <Link href="/my-card">
                          <Button
                            variant="outline"
                            className="h-11 w-full border-white/10 bg-transparent text-white hover:bg-white/[0.05]"
                          >
                            View My Card →
                          </Button>
                        </Link>
                      )}
                    </div>
                  </div>
                </div>
              </article>
            );
          })}
        </section>
      </div>
    </main>
  );
}