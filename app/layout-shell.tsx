"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  CalendarDays,
  ChartNoAxesCombined,
  CircleGauge,
  ClipboardList,
  CreditCard,
  LogIn,
  LogOut,
  MoreHorizontal,
  Settings,
  Sparkles,
  Trophy,
  TrendingUp,
  UserCircle2,
  X,
} from "lucide-react";
import { useAuth } from "./auth-context";

const primaryNav = [
  { label: "Home", href: "/", icon: CircleGauge },
  { label: "Briefing", href: "/briefing", icon: Sparkles },
  { label: "Opportunities", href: "/opportunities", icon: Trophy },
  { label: "My Card", href: "/my-card", icon: CreditCard },
];

// Bottom nav shows 4 primary items + "More"
const mobileBottomNav = [
  { label: "Home", href: "/", icon: CircleGauge },
  { label: "Games", href: "/games", icon: CalendarDays },
  { label: "Plays", href: "/opportunities", icon: Trophy },
  { label: "My Card", href: "/my-card", icon: CreditCard },
];

const researchNav = [
  { label: "Games", href: "/games", icon: CalendarDays },
  { label: "Line Movement", href: "/line-movement", icon: TrendingUp },
  { label: "Fantasy", href: "/fantasy", icon: ClipboardList },
  { label: "Performance", href: "/performance", icon: ChartNoAxesCombined },
];

export default function LayoutShell({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const [moreOpen, setMoreOpen] = useState(false);

  const isActive = (href: string) =>
    href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <div className="min-h-screen bg-[#070A0F] text-white">
      <div className="flex min-h-screen">
        {/* ── Desktop sidebar ─────────────────────────────────────── */}
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
                const active = isActive(item.href);

                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition ${active ? "bg-white/[0.07] text-white" : "text-zinc-500 hover:bg-white/[0.05] hover:text-white"}`}
                  >
                    <Icon
                      size={17}
                      strokeWidth={1.7}
                      className={active ? "text-white" : "text-zinc-600 transition group-hover:text-zinc-300"}
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
                const active = isActive(item.href);

                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition ${active ? "bg-white/[0.07] text-white" : "text-zinc-500 hover:bg-white/[0.05] hover:text-white"}`}
                  >
                    <Icon
                      size={17}
                      strokeWidth={1.7}
                      className={active ? "text-white" : "text-zinc-600 transition group-hover:text-zinc-300"}
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

              <div className="mt-4 border-t border-white/[0.06] pt-4 space-y-2">
                <Link href="/settings" className="flex items-center gap-2 text-xs text-zinc-600 transition hover:text-zinc-300">
                  <Settings size={14} />
                  Settings
                </Link>
                {user ? (
                  <>
                    <Link href="/settings" className="flex items-center gap-2 text-xs text-zinc-600 transition hover:text-zinc-300">
                      <UserCircle2 size={14} />
                      Profile
                    </Link>
                    <button onClick={logout} className="flex items-center gap-2 text-xs text-zinc-600 transition hover:text-zinc-300">
                      <LogOut size={14} />
                      Logout
                    </button>
                  </>
                ) : (
                  <Link href="/login" className="flex items-center gap-2 text-xs text-zinc-600 transition hover:text-zinc-300">
                    <LogIn size={14} />
                    Login
                  </Link>
                )}
              </div>
            </div>
          </div>
        </aside>

        {/* ── Page content ────────────────────────────────────────── */}
        <section className="min-w-0 flex-1 pb-20 lg:pb-0">
          {children}
        </section>
      </div>

      {/* ── Mobile bottom navigation bar (hidden on desktop) ────── */}
      <nav className="fixed bottom-0 left-0 right-0 z-40 border-t border-white/[0.08] bg-[#090D13]/95 backdrop-blur lg:hidden">
        <div className="flex h-16 items-stretch">
          {mobileBottomNav.map((item) => {
            const Icon = item.icon;
            const active = isActive(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex flex-1 flex-col items-center justify-center gap-1 text-[10px] transition ${active ? "text-white" : "text-zinc-500"}`}
              >
                <Icon size={20} strokeWidth={1.7} className={active ? "text-emerald-400" : "text-zinc-500"} />
                {item.label}
              </Link>
            );
          })}

          {/* "More" button opens the drawer */}
          <button
            onClick={() => setMoreOpen(true)}
            aria-label="More navigation options"
            className="flex flex-1 flex-col items-center justify-center gap-1 text-[10px] text-zinc-500 transition hover:text-white"
          >
            <MoreHorizontal size={20} strokeWidth={1.7} />
            More
          </button>
        </div>
      </nav>

      {/* ── "More" drawer (mobile) ───────────────────────────────── */}
      {moreOpen && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation menu">
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/60" onClick={() => setMoreOpen(false)} />

          {/* Sheet slides up from bottom */}
          <div className="absolute bottom-0 left-0 right-0 rounded-t-3xl border-t border-white/[0.08] bg-[#0B1119] p-6">
            <div className="mb-5 flex items-center justify-between">
              <p className="text-sm font-semibold text-white">Navigation</p>
              <button
                onClick={() => setMoreOpen(false)}
                aria-label="Close navigation menu"
                className="flex h-8 w-8 items-center justify-center rounded-full border border-white/10 text-zinc-400 hover:text-white"
              >
                <X size={16} />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-2">
              {[
                { label: "Briefing", href: "/briefing", icon: Sparkles },
                { label: "Line Movement", href: "/line-movement", icon: TrendingUp },
                { label: "Performance", href: "/performance", icon: ChartNoAxesCombined },
                { label: "Fantasy", href: "/fantasy", icon: ClipboardList },
                { label: "Settings", href: "/settings", icon: Settings },
              ].map((item) => {
                const Icon = item.icon;
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    onClick={() => setMoreOpen(false)}
                    className="flex items-center gap-3 rounded-2xl border border-white/[0.08] bg-white/[0.03] px-4 py-3 text-sm text-zinc-300 transition hover:bg-white/[0.06] hover:text-white"
                  >
                    <Icon size={17} strokeWidth={1.7} className="text-zinc-500" />
                    {item.label}
                  </Link>
                );
              })}
            </div>

            <div className="mt-4 border-t border-white/[0.06] pt-4">
              {user ? (
                <button
                  onClick={() => { logout(); setMoreOpen(false); }}
                  className="flex w-full items-center gap-3 rounded-2xl border border-white/[0.08] bg-white/[0.03] px-4 py-3 text-sm text-zinc-400 transition hover:text-white"
                >
                  <LogOut size={17} strokeWidth={1.7} />
                  Logout
                </button>
              ) : (
                <Link
                  href="/login"
                  onClick={() => setMoreOpen(false)}
                  className="flex items-center gap-3 rounded-2xl border border-white/[0.08] bg-white/[0.03] px-4 py-3 text-sm text-zinc-400 transition hover:text-white"
                >
                  <LogIn size={17} strokeWidth={1.7} />
                  Login
                </Link>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}