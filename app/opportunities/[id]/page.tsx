import Link from "next/link";
import { notFound } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { opportunities } from "@/data/opportunities";

type PageProps = {
  params: Promise<{
    id: string;
  }>;
};

export default async function OpportunityAnalysisPage({
  params,
}: PageProps) {
  const { id } = await params;

  const opportunity = opportunities.find((item) => item.id === id);

  if (!opportunity) {
    notFound();
  }

  const decisionFactors = [
    {
      label: "Model",
      value: "Strong",
      detail:
        "The current market remains favorable relative to our internal projection.",
      color: "text-emerald-400",
    },
    {
      label: "Injuries",
      value: "Relevant",
      detail:
        "Current injury information has been incorporated into the opportunity rating.",
      color: "text-emerald-400",
    },
    {
      label: "Market",
      value: "Monitor",
      detail:
        "The line may continue moving, so the quality of the available number matters.",
      color: "text-amber-400",
    },
    {
      label: "Weather",
      value: "Neutral",
      detail:
        "Current weather conditions do not materially change the recommendation.",
      color: "text-zinc-300",
    },
  ];

  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto max-w-6xl px-6 py-10 lg:px-10">

        <div className="flex items-center justify-between">
          <Link
            href="/opportunities"
            className="text-sm text-zinc-500 transition hover:text-white"
          >
            ← Opportunities
          </Link>

          <Badge
            variant="outline"
            className="border-emerald-400/20 bg-emerald-400/[0.05] text-emerald-400"
          >
            {opportunity.status}
          </Badge>
        </div>

        <section className="mt-12">
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-zinc-600">
            {opportunity.matchup}
          </p>

          <div className="mt-4 flex flex-col gap-8 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <h1 className="text-5xl font-semibold tracking-[-0.04em] md:text-7xl">
                {opportunity.pick}
              </h1>

              <p className="mt-4 text-base text-zinc-500">
                Best available at {opportunity.book}
              </p>
            </div>

            <div className="flex gap-10">
              <div>
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Confidence
                </p>

                <p className="mt-1 text-3xl font-semibold">
                  {opportunity.confidence}
                </p>
              </div>

              <div>
                <p className="text-[11px] uppercase tracking-[0.16em] text-zinc-700">
                  Model Edge
                </p>

                <p className="mt-1 text-3xl font-semibold text-emerald-400">
                  {opportunity.edge}
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="mt-10 rounded-3xl border border-white/[0.08] bg-[linear-gradient(135deg,#111823_0%,#0C121A_100%)] p-8 lg:p-10">
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-400">
            Executive Analysis
          </p>

          <h2 className="mt-3 max-w-4xl text-3xl font-semibold tracking-tight">
            Why this opportunity deserves your attention.
          </h2>

          <p className="mt-5 max-w-3xl text-base leading-8 text-zinc-400">
            {opportunity.reason}
          </p>

          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/my-card">
              <Button className="h-11 bg-white px-6 text-black hover:bg-zinc-200">
                Review My Card →
              </Button>
            </Link>

            <Link href="/opportunities">
              <Button
                variant="outline"
                className="h-11 border-white/10 bg-transparent px-6 text-white hover:bg-white/[0.05]"
              >
                Back to Opportunities
              </Button>
            </Link>
          </div>
        </section>

        <section className="mt-8">
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-700">
            Decision Factors
          </p>

          <div className="mt-4 grid gap-4 md:grid-cols-2">
            {decisionFactors.map((factor) => (
              <article
                key={factor.label}
                className="rounded-2xl border border-white/[0.07] bg-[#0D131C] p-6"
              >
                <div className="flex items-center justify-between">
                  <p className="text-sm text-zinc-500">{factor.label}</p>

                  <p className={`text-sm font-medium ${factor.color}`}>
                    {factor.value}
                  </p>
                </div>

                <p className="mt-4 text-sm leading-7 text-zinc-500">
                  {factor.detail}
                </p>
              </article>
            ))}
          </div>
        </section>

        <section className="mt-8 grid gap-4 lg:grid-cols-2">
          <article className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-700">
              Why We Like It
            </p>

            <h3 className="mt-3 text-2xl font-semibold">
              Current evidence supports this position.
            </h3>

            <p className="mt-4 text-sm leading-7 text-zinc-500">
              The model edge, current market price, and relevant contextual
              factors combine to keep this opportunity above the current
              decision threshold.
            </p>
          </article>

          <article className="rounded-3xl border border-white/[0.08] bg-[#0D131C] p-7">
            <p className="text-xs font-medium uppercase tracking-[0.18em] text-zinc-700">
              Biggest Risks
            </p>

            <div className="mt-5 space-y-5">
              <div>
                <p className="font-medium">Market movement</p>
                <p className="mt-1 text-sm leading-6 text-zinc-500">
                  A worse number can materially reduce the expected edge.
                </p>
              </div>

              <div>
                <p className="font-medium">Late injury information</p>
                <p className="mt-1 text-sm leading-6 text-zinc-500">
                  New inactive or injury news can change the recommendation.
                </p>
              </div>

              <div>
                <p className="font-medium">Model uncertainty</p>
                <p className="mt-1 text-sm leading-6 text-zinc-500">
                  Confidence reflects uncertainty and should never be treated as
                  a guaranteed outcome.
                </p>
              </div>
            </div>
          </article>
        </section>

        <section className="mt-8 rounded-3xl border border-emerald-400/15 bg-emerald-400/[0.035] p-8">
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-emerald-400">
            Bottom Line
          </p>

          <h2 className="mt-3 text-3xl font-semibold">
            {opportunity.pick} remains actionable at the current number.
          </h2>

          <p className="mt-4 max-w-3xl text-sm leading-7 text-zinc-400">
            The opportunity currently remains above our threshold, but the
            recommendation should be reassessed if the market, injury picture,
            or other material inputs change before kickoff.
          </p>
        </section>

      </div>
    </main>
  );
}