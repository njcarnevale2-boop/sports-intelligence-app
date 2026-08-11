import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const demoCards = [
  { title: "Dashboard", description: "Live market pulse, edge, and score trends" },
  { title: "Opportunities", description: "Ranked plays with support and conviction" },
  { title: "Full Analysis", description: "Explainable reasoning behind each recommendation" },
  { title: "Line Movement", description: "Book movement, steam, and market confirmation" },
  { title: "Executive Briefing", description: "Readable summaries for fast decision-making" },
];

const features = [
  { title: "Sports Intelligence Score", description: "A holistic score combining edge, expected value, confidence, market signal, and data completeness." },
  { title: "Market Intelligence", description: "Track sharp line movement, steam, consensus, and support from key books." },
  { title: "Executive Analysis", description: "Readable, actionable writeups that explain not just what to bet, but why it matters." },
  { title: "Injury Intelligence", description: "Quantify roster burden and matchup-specific injury edges in a single view." },
  { title: "Weather Intelligence", description: "Evaluate weather impact on efficiency, tempo, and game script." },
  { title: "Closing Line Value", description: "Coming soon: track how your edges persist against the closing market." },
];

const faqs = [
  {
    question: "What makes Sports Intelligence different?",
    answer: "Rather than presenting a list of picks, the platform combines multiple signals into a single explainable decision engine so you can understand the reasoning behind every score.",
  },
  {
    question: "Is this for casual bettors or professionals?",
    answer: "The system is designed for serious bettors who want a premium decision layer with transparency, market context, and structured analysis.",
  },
  {
    question: "How does the beta work?",
    answer: "Private beta access is limited to founding members and enterprise partners. Early users receive access to the platform and can help shape the roadmap.",
  },
];

export default function MarketingPage() {
  return (
    <main className="min-h-screen bg-[#05070B] text-white">
      <section className="border-b border-white/10 bg-[radial-gradient(circle_at_top_left,_rgba(56,189,248,0.18),_transparent_32%),linear-gradient(135deg,_#06080C_0%,_#0B1119_100%)]">
        <div className="mx-auto flex max-w-7xl flex-col px-6 py-20 lg:px-10 lg:py-28">
          <div className="flex flex-wrap items-center gap-3">
            <Badge className="border-sky-400/30 bg-sky-400/10 text-sky-300">Private Beta</Badge>
            <p className="text-sm text-zinc-400">Explainable AI for modern betting intelligence</p>
          </div>

          <div className="mt-10 grid items-center gap-12 lg:grid-cols-[1.1fr_0.9fr]">
            <div className="max-w-2xl">
              <h1 className="text-4xl font-semibold tracking-tight text-white sm:text-5xl lg:text-6xl">
                Sports Intelligence for Serious Bettors
              </h1>
              <p className="mt-6 text-lg leading-8 text-zinc-400 sm:text-xl">
                Make smarter betting decisions with explainable AI, market intelligence, injury analysis, weather context, and proprietary Sports Intelligence Scores.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Link href="#pricing">
                  <Button className="h-12 rounded-full bg-white px-6 text-base font-medium text-black hover:bg-zinc-200">
                    Join the Private Beta
                  </Button>
                </Link>
                <Link href="#demo">
                  <Button variant="outline" className="h-12 rounded-full border-white/15 bg-white/5 px-6 text-base font-medium text-white hover:bg-white/10">
                    Explore the Platform
                  </Button>
                </Link>
              </div>
            </div>

            <div className="rounded-3xl border border-white/10 bg-[#081018]/80 p-6 shadow-2xl shadow-sky-950/20 backdrop-blur">
              <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-zinc-500">Top opportunity</p>
                    <p className="mt-1 text-xl font-semibold">Bills -1.5 vs. Dolphins</p>
                  </div>
                  <div className="rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-sm font-medium text-emerald-400">A+</div>
                </div>
                <div className="mt-6 grid gap-3 sm:grid-cols-3">
                  <div className="rounded-2xl border border-white/10 bg-[#0D141D] p-3">
                    <p className="text-[11px] uppercase tracking-[0.22em] text-zinc-600">Score</p>
                    <p className="mt-2 text-2xl font-semibold text-sky-400">91</p>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-[#0D141D] p-3">
                    <p className="text-[11px] uppercase tracking-[0.22em] text-zinc-600">Edge</p>
                    <p className="mt-2 text-2xl font-semibold text-white">+6.8%</p>
                  </div>
                  <div className="rounded-2xl border border-white/10 bg-[#0D141D] p-3">
                    <p className="text-[11px] uppercase tracking-[0.22em] text-zinc-600">Market</p>
                    <p className="mt-2 text-2xl font-semibold text-amber-400">Confirming</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="demo" className="mx-auto max-w-7xl px-6 py-20 lg:px-10">
        <div className="max-w-2xl">
          <p className="text-sm font-medium uppercase tracking-[0.24em] text-sky-400">Product Demo</p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">A premium view into every decision layer</h2>
          <p className="mt-4 text-lg text-zinc-400">From the central dashboard to deep analysis, each surface is designed to help you move from signal to action with clarity.</p>
        </div>

        <div className="mt-10 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {demoCards.map((card, index) => (
            <div key={card.title} className="rounded-3xl border border-white/10 bg-[#0B1119] p-6 shadow-lg shadow-black/20">
              <div className="flex h-40 items-center justify-center rounded-2xl border border-dashed border-white/10 bg-gradient-to-br from-white/5 to-white/0">
                <div className="text-center">
                  <p className="text-sm text-zinc-500">{index + 1}.0</p>
                  <p className="mt-2 text-xl font-semibold text-white">{card.title}</p>
                  <p className="mt-2 text-sm text-zinc-400">{card.description}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-6 py-20 lg:px-10">
        <div className="max-w-2xl">
          <p className="text-sm font-medium uppercase tracking-[0.24em] text-sky-400">Features</p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">Everything serious bettors need, organized into one engine</h2>
        </div>

        <div className="mt-10 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {features.map((feature) => (
            <div key={feature.title} className="rounded-3xl border border-white/10 bg-[#0B1119] p-6">
              <h3 className="text-xl font-semibold text-white">{feature.title}</h3>
              <p className="mt-3 text-sm leading-7 text-zinc-400">{feature.description}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-6 py-20 lg:px-10">
        <div className="rounded-3xl border border-white/10 bg-[#0B1119] p-8 lg:p-10">
          <p className="text-sm font-medium uppercase tracking-[0.24em] text-sky-400">Why We&apos;re Different</p>
          <div className="mt-6 grid gap-6 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
            <div>
              <h2 className="text-3xl font-semibold tracking-tight text-white sm:text-4xl">We combine signals into one decision engine, not just another picks feed.</h2>
            </div>
            <div className="space-y-4 text-lg leading-8 text-zinc-400">
              <p>Sports Intelligence evaluates market structure, expected value, confidence, injury burden, and weather impact together so you can see the full picture behind each opportunity.</p>
              <p>Every recommendation is paired with explainable reasoning, giving you confidence in the model and clarity in the decision.</p>
            </div>
          </div>
        </div>
      </section>

      <section id="pricing" className="mx-auto max-w-7xl px-6 py-20 lg:px-10">
        <div className="max-w-2xl">
          <p className="text-sm font-medium uppercase tracking-[0.24em] text-sky-400">Pricing</p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">Access the platform during the private beta</h2>
        </div>

        <div className="mt-10 grid gap-5 lg:grid-cols-3">
          <div className="rounded-3xl border border-white/10 bg-[#0B1119] p-8">
            <p className="text-lg font-semibold text-white">Private Beta</p>
            <p className="mt-3 text-sm leading-7 text-zinc-400">Founding access to early product releases and direct roadmap input.</p>
            <p className="mt-6 text-4xl font-semibold text-white">Contact</p>
            <Link href="mailto:beta@sportsintel.app" className="mt-8 block">
              <Button className="w-full rounded-full bg-white text-black hover:bg-zinc-200">Request Access</Button>
            </Link>
          </div>

          <div className="rounded-3xl border border-sky-400/20 bg-sky-400/10 p-8">
            <p className="text-lg font-semibold text-white">Founding Member</p>
            <p className="mt-3 text-sm leading-7 text-zinc-300">Priority access, premium support, and early feature unlocks.</p>
            <p className="mt-6 text-4xl font-semibold text-white">$499/mo</p>
            <Link href="mailto:beta@sportsintel.app" className="mt-8 block">
              <Button className="w-full rounded-full bg-sky-400 text-black hover:bg-sky-300">Reserve Your Spot</Button>
            </Link>
          </div>

          <div className="rounded-3xl border border-white/10 bg-[#0B1119] p-8">
            <p className="text-lg font-semibold text-white">Enterprise</p>
            <p className="mt-3 text-sm leading-7 text-zinc-400">Custom integrations, workflow support, and dedicated onboarding.</p>
            <p className="mt-6 text-4xl font-semibold text-white">Coming Soon</p>
            <Link href="mailto:beta@sportsintel.app" className="mt-8 block">
              <Button variant="outline" className="w-full rounded-full border-white/15 bg-white/5 text-white hover:bg-white/10">Get in Touch</Button>
            </Link>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-6 py-20 lg:px-10">
        <div className="max-w-2xl">
          <p className="text-sm font-medium uppercase tracking-[0.24em] text-sky-400">FAQ</p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">Common questions about the platform</h2>
        </div>

        <div className="mt-10 space-y-4">
          {faqs.map((faq) => (
            <div key={faq.question} className="rounded-3xl border border-white/10 bg-[#0B1119] p-6">
              <h3 className="text-lg font-semibold text-white">{faq.question}</h3>
              <p className="mt-3 text-sm leading-7 text-zinc-400">{faq.answer}</p>
            </div>
          ))}
        </div>
      </section>

      <footer className="border-t border-white/10 bg-[#05070B]">
        <div className="mx-auto flex max-w-7xl flex-col gap-3 px-6 py-8 text-sm text-zinc-500 lg:flex-row lg:items-center lg:justify-between lg:px-10">
          <p>Sports Intelligence © 2026</p>
          <div className="flex gap-4">
            <Link href="#demo" className="hover:text-white">Demo</Link>
            <Link href="#pricing" className="hover:text-white">Pricing</Link>
            <Link href="mailto:beta@sportsintel.app" className="hover:text-white">Contact</Link>
          </div>
        </div>
      </footer>
    </main>
  );
}
