import {
  AlertCard,
  AnimationDemo,
  ConfidenceDisplay,
  DarkModeValidation,
  EmptyState,
  ErrorState,
  GameCard,
  InsightCard,
  MarketGradeDisplay,
  MetricCard,
  RadiusSwatch,
  ResponsivePreview,
  ShadowSwatch,
  SkeletonLoader,
  SiaBadge,
  SiaButton,
  SpacingScale,
  SportsIntelligenceScoreDisplay,
  TokenSwatch,
  TypographySample,
} from "@/components/design-system/sia-design-system";

export default function DesignSystemPage() {
  return (
    <main className="min-h-screen bg-[#070A0F] text-white">
      <div className="mx-auto flex max-w-7xl flex-col gap-8 px-6 py-10 lg:px-10">
        <section className="rounded-[36px] border border-white/10 bg-[radial-gradient(circle_at_top_left,_rgba(16,185,129,0.16),_transparent_40%),linear-gradient(135deg,_rgba(255,255,255,0.05),_transparent)] p-8 shadow-[0_30px_120px_rgba(0,0,0,0.28)]">
          <p className="text-[11px] uppercase tracking-[0.24em] text-emerald-400">SIA Design System</p>
          <h1 className="mt-4 text-4xl font-semibold tracking-[-0.03em] md:text-6xl">One visual language for every Sports Intelligence experience.</h1>
          <p className="mt-4 max-w-3xl text-base leading-7 text-zinc-400">This page intentionally captures the shared foundations for buttons, cards, badges, scores, spacing, motion, and states without changing product behavior.</p>
        </section>

        <section className="grid gap-6 lg:grid-cols-[1.3fr_0.9fr]">
          <div className="rounded-[28px] border border-white/10 bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Buttons</p>
            <div className="mt-5 flex flex-wrap gap-3">
              <SiaButton>Primary</SiaButton>
              <SiaButton variant="secondary">Secondary</SiaButton>
              <SiaButton variant="danger">Danger</SiaButton>
              <SiaButton variant="ghost">Ghost</SiaButton>
              <SiaButton variant="icon">✦</SiaButton>
            </div>
          </div>
          <div className="rounded-[28px] border border-white/10 bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Badges</p>
            <div className="mt-4 flex flex-wrap gap-3">
              <SiaBadge tone="elite">Elite Opportunity</SiaBadge>
              <SiaBadge tone="strong">Strong Bet</SiaBadge>
              <SiaBadge tone="lean">Lean</SiaBadge>
              <SiaBadge tone="pass">Pass</SiaBadge>
              <SiaBadge tone="avoid">Avoid</SiaBadge>
            </div>
          </div>
        </section>

        <section className="grid gap-6 lg:grid-cols-2">
          <div className="rounded-[28px] border border-white/10 bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Cards</p>
            <div className="mt-5 grid gap-4">
              <GameCard title="Bills at Chiefs" subtitle="A premium matchup card that can be reused across the product." footer="Strong market pressure on the spread" highlight />
              <InsightCard title="Why this setup matters" description="A reusable insight panel for context, rationale, and supporting evidence." footer="Model confidence remains high" />
              <AlertCard title="Live alert" description="The warning tone keeps the viewer informed without disrupting the flow." tone="warning" />
            </div>
          </div>

          <div className="rounded-[28px] border border-white/10 bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Score displays</p>
            <div className="mt-5 grid gap-4 md:grid-cols-3">
              <SportsIntelligenceScoreDisplay value={92} />
              <MarketGradeDisplay value="Elite Opportunity" />
              <ConfidenceDisplay value={87} />
            </div>
          </div>
        </section>

        <section className="rounded-[28px] border border-white/10 bg-[#0D131C] p-6">
          <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Colors</p>
          <div className="mt-5 grid gap-4 md:grid-cols-3 lg:grid-cols-6">
            <TokenSwatch name="Primary" value="#10B981" />
            <TokenSwatch name="Secondary" value="#38BDF8" />
            <TokenSwatch name="Success" value="#34D399" />
            <TokenSwatch name="Warning" value="#F59E0B" />
            <TokenSwatch name="Danger" value="#FB7185" />
            <TokenSwatch name="Surface" value="#0B1119" />
          </div>
        </section>

        <section className="grid gap-6 lg:grid-cols-2">
          <div className="rounded-[28px] border border-white/10 bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Typography</p>
            <div className="mt-5 grid gap-4">
              <TypographySample title="Display" description="High-contrast heading treatment for hero moments." />
              <TypographySample title="Heading" description="Section headers maintain a clear hierarchy and rhythm." />
              <TypographySample title="Title" description="Card and panel titles should stay crisp and direct." />
              <TypographySample title="Body" description="Body copy uses a lighter touch so analysis remains readable." tone="muted" />
            </div>
          </div>

          <div className="rounded-[28px] border border-white/10 bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Metrics</p>
            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <MetricCard label="Total signal" value="24" hint="Live opportunities" accent="emerald" />
              <MetricCard label="Avg edge" value="+4.8%" hint="Movement over baseline" accent="sky" />
              <MetricCard label="Risk" value="Balanced" hint="Portfolio remains controlled" accent="amber" />
              <MetricCard label="Alerts" value="3" hint="Action needed" accent="rose" />
            </div>
          </div>
        </section>

        <section className="grid gap-6 lg:grid-cols-2">
          <div className="rounded-[28px] border border-white/10 bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Spacing scale</p>
            <div className="mt-5">
              <SpacingScale />
            </div>
          </div>
          <div className="rounded-[28px] border border-white/10 bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Shadows & radius</p>
            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <ShadowSwatch name="Soft" className="shadow-[0_16px_40px_rgba(0,0,0,0.24)]" />
              <ShadowSwatch name="Elevated" className="shadow-[0_24px_80px_rgba(0,0,0,0.28)]" />
              <RadiusSwatch name="Rounded" className="rounded-[12px]" />
              <RadiusSwatch name="Pill" className="rounded-full" />
            </div>
          </div>
        </section>

        <section className="grid gap-6 lg:grid-cols-2">
          <div className="rounded-[28px] border border-white/10 bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Animations</p>
            <div className="mt-5">
              <AnimationDemo />
            </div>
          </div>
          <div className="rounded-[28px] border border-white/10 bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Skeleton loaders</p>
            <div className="mt-5">
              <SkeletonLoader />
            </div>
          </div>
        </section>

        <section className="grid gap-6 lg:grid-cols-2">
          <div className="rounded-[28px] border border-white/10 bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Empty states</p>
            <div className="mt-5">
              <EmptyState />
            </div>
          </div>
          <div className="rounded-[28px] border border-white/10 bg-[#0D131C] p-6">
            <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Error states</p>
            <div className="mt-5">
              <ErrorState />
            </div>
          </div>
        </section>

        <section className="rounded-[28px] border border-white/10 bg-[#0D131C] p-6">
          <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Mobile responsive examples</p>
          <div className="mt-5">
            <ResponsivePreview />
          </div>
        </section>

        <section className="rounded-[28px] border border-white/10 bg-[#0D131C] p-6">
          <p className="text-[11px] uppercase tracking-[0.24em] text-zinc-600">Dark mode validation</p>
          <div className="mt-5">
            <DarkModeValidation />
          </div>
        </section>
      </div>
    </main>
  );
}
