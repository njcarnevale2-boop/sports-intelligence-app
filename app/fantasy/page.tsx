"use client";

import Link from "next/link";

const plannedModules = [
  {
    title: "Player projections",
    description: "Projection models and expected usage for the slate.",
  },
  {
    title: "Matchup grades",
    description: "Targeted matchup context that accounts for pace, pressure, and defense.",
  },
  {
    title: "Injury-adjusted projections",
    description: "Late-week waiver and role-change adjustments that update the projection floor.",
  },
  {
    title: "Usage trends",
    description: "Role and snap-share trends that are often the clearest signal in DFS and season-long research.",
  },
  {
    title: "Start/Sit intelligence",
    description: "Decision support for lineup construction and weekly roster management.",
  },
  {
    title: "DFS value",
    description: "Top leverage ideas and captain or value considerations when the slate is live.",
  },
];

export default function FantasyPage() {
  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-6xl px-6 py-10 lg:px-10">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Fantasy research</p>
            <h1 className="mt-3 text-4xl font-semibold tracking-tight">Fantasy</h1>
            <p className="mt-3 max-w-2xl text-sm leading-7 text-zinc-500">
              Fantasy Intelligence is currently in development. The experience below outlines the modules that will be released as the platform matures.
            </p>
          </div>

          <Link
            href="/"
            className="rounded-full border border-white/10 px-4 py-2 text-sm text-zinc-300 transition hover:border-white/20 hover:text-white"
          >
            Back to home
          </Link>
        </div>

        <section className="mt-10 rounded-3xl border border-white/10 bg-[#0B1119] p-8 shadow-2xl shadow-black/25">
          <div className="max-w-3xl">
            <p className="text-[10px] uppercase tracking-[0.2em] text-zinc-600">Development status</p>
            <h2 className="mt-3 text-3xl font-semibold tracking-tight">Professional fantasy research is on the roadmap.</h2>
            <p className="mt-4 text-sm leading-7 text-zinc-500">
              This page intentionally avoids fake data. It is a placeholder for the upcoming fantasy intelligence experience, which will eventually connect to live projection feeds and injury-adjustment services.
            </p>
          </div>

          <div className="mt-8 grid gap-4 md:grid-cols-2">
            {plannedModules.map((module) => (
              <div key={module.title} className="rounded-2xl border border-white/10 bg-black/20 p-5">
                <p className="text-lg font-semibold text-white">{module.title}</p>
                <p className="mt-2 text-sm leading-7 text-zinc-500">{module.description}</p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}
