import Link from "next/link";
import {
  ChartNoAxesCombined,
  CircleGauge,
  ClipboardList,
  CreditCard,
  Gamepad2,
  Settings,
  Sparkles,
  Trophy,
  TrendingUp,
} from "lucide-react";

const primaryNav = [
  { label: "Home", href: "/", icon: CircleGauge },
  { label: "Briefing", href: "/briefing", icon: Sparkles },
  { label: "Opportunities", href: "/opportunities", icon: Trophy },
  { label: "My Card", href: "/my-card", icon: CreditCard },
];

const researchNav = [
  { label: "Games", href: "/games", icon: Gamepad2 },
  { label: "Line Movement", href: "/line-movement", icon: TrendingUp },
  { label: "Fantasy", href: "/fantasy", icon: ClipboardList },
  { label: "Performance", href: "/performance", icon: ChartNoAxesCombined },
];

export default function LayoutShell({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-[#070A0F] text-white">
      <div className="flex min-h-screen">
        <aside className="hidden w-[248px] shrink-0 border-r border-white/[0.06] bg-[#090D13] lg:flex lg:flex-col">
          <div className="px-5 pt-6">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-white/[0.08] bg-white/[0.04] font-semibold">
                SI
              </div>

              <div>
                <p className="text-sm font-semibold tracking-tight">
                  Sports Intelligence
                </p>

                <p className="mt-0.5 text-[11px] text-zinc-600">
                  NFL Decision Platform
                </p>
              </div>
            </div>
          </div>

          <div className="mt-10 px-3">
            <p className="px-3 text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-700">
              Today
            </p>

            <nav className="mt-3 space-y-1">
              {primaryNav.map((item) => {
                const Icon = item.icon;

                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-zinc-500 transition hover:bg-white/[0.05] hover:text-white"
                  >
                    <Icon
                      size={17}
                      strokeWidth={1.7}
                      className="text-zinc-600 transition group-hover:text-zinc-300"
                    />

                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </div>

          <div className="mt-8 px-3">
            <p className="px-3 text-[10px] font-medium uppercase tracking-[0.18em] text-zinc-700">
              Research
            </p>

            <nav className="mt-3 space-y-1">
              {researchNav.map((item) => {
                const Icon = item.icon;

                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className="group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-zinc-500 transition hover:bg-white/[0.05] hover:text-white"
                  >
                    <Icon
                      size={17}
                      strokeWidth={1.7}
                      className="text-zinc-600 transition group-hover:text-zinc-300"
                    />

                    {item.label}
                  </Link>
                );
              })}
            </nav>
          </div>

          <div className="mt-auto p-4">
            <div className="rounded-2xl border border-white/[0.06] bg-white/[0.025] p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium text-zinc-300">
                    Intelligence Engine
                  </p>

                  <p className="mt-1 text-[11px] text-zinc-600">
                    Monitoring today&apos;s slate
                  </p>
                </div>

                <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_12px_rgba(52,211,153,0.7)]" />
              </div>

              <div className="mt-4 border-t border-white/[0.06] pt-4">
                <Link
                  href="/settings"
                  className="flex items-center gap-2 text-xs text-zinc-600 transition hover:text-zinc-300"
                >
                  <Settings size={14} />
                  Settings
                </Link>
              </div>
            </div>
          </div>
        </aside>

        <section className="min-w-0 flex-1">
          {children}
        </section>
      </div>
    </div>
  );
}