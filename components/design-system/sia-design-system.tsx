import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type ButtonVariant = "primary" | "secondary" | "danger" | "ghost" | "icon";

type SiaButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode;
  className?: string;
  variant?: ButtonVariant;
};

type BadgeTone = "elite" | "strong" | "lean" | "pass" | "avoid";

type MetricCardProps = {
  label: string;
  value: string;
  hint?: string;
  accent?: "emerald" | "sky" | "amber" | "rose";
};

type InsightCardProps = {
  title: string;
  description: string;
  footer?: string;
};

type AlertCardProps = {
  title: string;
  description: string;
  tone?: "success" | "warning" | "danger";
};

type ScoreDisplayProps = {
  value: number;
  label?: string;
  accent?: "emerald" | "sky" | "amber" | "rose";
};

type TokenSwatchProps = {
  name: string;
  value: string;
  className?: string;
};

function SiaPrimaryButton({ children, className, variant: _variant, ...props }: SiaButtonProps) {
  return (
    <Button variant="default" className={cn("bg-emerald-500 text-black hover:bg-emerald-400", className)} {...props}>
      {children}
    </Button>
  );
}

function SiaSecondaryButton({ children, className, variant: _variant, ...props }: SiaButtonProps) {
  return (
    <Button variant="secondary" className={cn("bg-white/10 text-white hover:bg-white/20", className)} {...props}>
      {children}
    </Button>
  );
}

function SiaDangerButton({ children, className, variant: _variant, ...props }: SiaButtonProps) {
  return (
    <Button variant="destructive" className={cn("bg-rose-500/15 text-rose-300 hover:bg-rose-500/25", className)} {...props}>
      {children}
    </Button>
  );
}

function SiaGhostButton({ children, className, variant: _variant, ...props }: SiaButtonProps) {
  return (
    <Button variant="ghost" className={cn("text-zinc-300 hover:bg-white/10 hover:text-white", className)} {...props}>
      {children}
    </Button>
  );
}

function SiaIconButton({ children, className, variant: _variant, ...props }: SiaButtonProps) {
  return (
    <Button variant="ghost" size="icon" className={cn("rounded-full border border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10 hover:text-white", className)} {...props}>
      {children}
    </Button>
  );
}

function SiaButton({ variant = "primary", children, className, ...props }: SiaButtonProps) {
  switch (variant) {
    case "secondary":
      return <SiaSecondaryButton className={className} {...props}>{children}</SiaSecondaryButton>;
    case "danger":
      return <SiaDangerButton className={className} {...props}>{children}</SiaDangerButton>;
    case "ghost":
      return <SiaGhostButton className={className} {...props}>{children}</SiaGhostButton>;
    case "icon":
      return <SiaIconButton className={className} {...props}>{children}</SiaIconButton>;
    default:
      return <SiaPrimaryButton className={className} {...props}>{children}</SiaPrimaryButton>;
  }
}

function SiaBadge({ tone = "strong", children }: { tone?: BadgeTone; children: ReactNode }) {
  const styles = {
    elite: "border-emerald-400/20 bg-emerald-400/10 text-emerald-300",
    strong: "border-sky-400/20 bg-sky-400/10 text-sky-300",
    lean: "border-amber-400/20 bg-amber-400/10 text-amber-300",
    pass: "border-zinc-500/20 bg-zinc-500/10 text-zinc-300",
    avoid: "border-rose-400/20 bg-rose-400/10 text-rose-300",
  } as const;

  return <span className={cn("inline-flex items-center rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.22em]", styles[tone])}>{children}</span>;
}

function GameCard({ title, subtitle, footer, highlight = false }: { title: string; subtitle: string; footer?: string; highlight?: boolean }) {
  return (
    <article className={cn("rounded-[24px] border border-white/10 bg-[#0B1119] p-5 shadow-[0_24px_80px_rgba(0,0,0,0.28)] transition-all duration-300 hover:-translate-y-1 hover:border-emerald-400/20", highlight && "ring-1 ring-emerald-400/20") }>
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">Game card</p>
          <h3 className="mt-2 text-lg font-semibold text-white">{title}</h3>
        </div>
        <SiaBadge tone={highlight ? "elite" : "strong"}>{highlight ? "Elite" : "Live"}</SiaBadge>
      </div>
      <p className="mt-3 text-sm leading-7 text-zinc-400">{subtitle}</p>
      {footer ? <p className="mt-4 text-sm font-medium text-emerald-400">{footer}</p> : null}
    </article>
  );
}

function MetricCard({ label, value, hint, accent = "emerald" }: MetricCardProps) {
  const accentStyles = {
    emerald: "border-emerald-400/20 bg-emerald-400/10 text-emerald-300",
    sky: "border-sky-400/20 bg-sky-400/10 text-sky-300",
    amber: "border-amber-400/20 bg-amber-400/10 text-amber-300",
    rose: "border-rose-400/20 bg-rose-400/10 text-rose-300",
  } as const;

  return (
    <div className={cn("rounded-[20px] border border-white/10 bg-[#0D131C] p-4", accentStyles[accent])}>
      <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">{label}</p>
      <p className="mt-3 text-2xl font-semibold text-white">{value}</p>
      {hint ? <p className="mt-2 text-sm text-zinc-400">{hint}</p> : null}
    </div>
  );
}

function InsightCard({ title, description, footer }: InsightCardProps) {
  return (
    <div className="rounded-[24px] border border-white/10 bg-[#0B1119] p-5 shadow-[0_20px_60px_rgba(0,0,0,0.24)] transition-all duration-300 hover:-translate-y-1">
      <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">Insight</p>
      <h3 className="mt-3 text-lg font-semibold text-white">{title}</h3>
      <p className="mt-3 text-sm leading-7 text-zinc-400">{description}</p>
      {footer ? <p className="mt-4 text-sm font-medium text-emerald-400">{footer}</p> : null}
    </div>
  );
}

function AlertCard({ title, description, tone = "success" }: AlertCardProps) {
  const styles = {
    success: "border-emerald-400/20 bg-emerald-400/10 text-emerald-300",
    warning: "border-amber-400/20 bg-amber-400/10 text-amber-300",
    danger: "border-rose-400/20 bg-rose-400/10 text-rose-300",
  } as const;

  return (
    <div className={cn("rounded-[22px] border p-4", styles[tone])}>
      <p className="text-sm font-semibold">{title}</p>
      <p className="mt-2 text-sm leading-7 opacity-90">{description}</p>
    </div>
  );
}

function SportsIntelligenceScoreDisplay({ value, label = "SI Score", accent = "emerald" }: ScoreDisplayProps) {
  const accentStyles = {
    emerald: "text-emerald-400",
    sky: "text-sky-400",
    amber: "text-amber-400",
    rose: "text-rose-400",
  } as const;

  return (
    <div className="rounded-[22px] border border-white/10 bg-[#0D131C] p-4">
      <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">{label}</p>
      <p className={cn("mt-3 text-3xl font-semibold", accentStyles[accent])}>{value}</p>
    </div>
  );
}

function MarketGradeDisplay({ value, label = "Market Grade" }: { value: string; label?: string }) {
  return (
    <div className="rounded-[22px] border border-white/10 bg-[#0D131C] p-4">
      <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">{label}</p>
      <p className="mt-3 text-lg font-semibold text-white">{value}</p>
    </div>
  );
}

function ConfidenceDisplay({ value, label = "Confidence" }: { value: number; label?: string }) {
  return (
    <div className="rounded-[22px] border border-white/10 bg-[#0D131C] p-4">
      <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">{label}</p>
      <p className="mt-3 text-2xl font-semibold text-white">{value}%</p>
    </div>
  );
}

function TokenSwatch({ name, value, className }: TokenSwatchProps) {
  return (
    <div className={cn("rounded-[18px] border border-white/10 bg-[#0D131C] p-4", className)}>
      <div className="h-12 rounded-[14px] border border-white/10" style={{ backgroundColor: value }} />
      <p className="mt-3 text-sm font-semibold text-white">{name}</p>
      <p className="mt-1 text-xs uppercase tracking-[0.2em] text-zinc-500">{value}</p>
    </div>
  );
}

function TypographySample({ title, description, tone = "default" }: { title: string; description: string; tone?: "default" | "muted" }) {
  const tones = {
    default: "text-white",
    muted: "text-zinc-400",
  } as const;

  return (
    <div className="rounded-[20px] border border-white/10 bg-[#0D131C] p-4">
      <p className="text-[10px] uppercase tracking-[0.24em] text-zinc-600">Typography</p>
      <p className={cn("mt-3 text-2xl font-semibold", tones[tone])}>{title}</p>
      <p className="mt-2 text-sm leading-7 text-zinc-400">{description}</p>
    </div>
  );
}

function SpacingScale() {
  return (
    <div className="space-y-3">
      {[
        { name: "XS", size: "8px", className: "h-2" },
        { name: "SM", size: "12px", className: "h-3" },
        { name: "MD", size: "16px", className: "h-4" },
        { name: "LG", size: "24px", className: "h-6" },
        { name: "XL", size: "32px", className: "h-8" },
        { name: "2XL", size: "48px", className: "h-12" },
      ].map((token) => (
        <div key={token.name} className="flex items-center gap-4 rounded-[16px] border border-white/10 bg-[#0D131C] p-3">
          <div className="w-20 text-sm font-semibold text-white">{token.name}</div>
          <div className={cn("w-full rounded-full bg-emerald-400/20", token.className)} />
          <div className="text-sm text-zinc-500">{token.size}</div>
        </div>
      ))}
    </div>
  );
}

function ShadowSwatch({ name, className }: { name: string; className: string }) {
  return (
    <div className="rounded-[20px] border border-white/10 bg-[#0D131C] p-4">
      <div className={cn("h-20 rounded-[18px] border border-white/10 bg-[#111827]", className)} />
      <p className="mt-3 text-sm font-semibold text-white">{name}</p>
    </div>
  );
}

function RadiusSwatch({ name, className }: { name: string; className: string }) {
  return (
    <div className="rounded-[20px] border border-white/10 bg-[#0D131C] p-4">
      <div className={cn("h-16 border border-white/10 bg-[#111827]", className)} />
      <p className="mt-3 text-sm font-semibold text-white">{name}</p>
    </div>
  );
}

function AnimationDemo() {
  return (
    <div className="rounded-[24px] border border-white/10 bg-[#0B1119] p-5 transition-all duration-300 hover:-translate-y-1 hover:border-emerald-400/20">
      <p className="text-sm text-zinc-400">Hover animation, loading shimmer, and transition states all conform to the same motion language.</p>
    </div>
  );
}

function SkeletonLoader() {
  return (
    <div className="space-y-3 rounded-[24px] border border-white/10 bg-[#0B1119] p-5">
      <div className="h-3 w-24 animate-pulse rounded-full bg-white/10" />
      <div className="h-4 w-full animate-pulse rounded-full bg-white/10" />
      <div className="h-4 w-4/5 animate-pulse rounded-full bg-white/10" />
      <div className="h-12 w-full animate-pulse rounded-[16px] bg-white/10" />
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-[24px] border border-dashed border-white/10 bg-[#0D131C] p-8 text-center">
      <p className="text-lg font-semibold text-white">No signals yet</p>
      <p className="mt-2 text-sm leading-7 text-zinc-400">This state keeps the layout calm and informative while the system gathers data.</p>
    </div>
  );
}

function ErrorState() {
  return (
    <div className="rounded-[24px] border border-rose-400/20 bg-rose-400/10 p-6 text-center">
      <p className="text-lg font-semibold text-rose-300">Something went wrong</p>
      <p className="mt-2 text-sm leading-7 text-rose-200">Use a concise, recoverable message that keeps the user oriented.</p>
    </div>
  );
}

function ResponsivePreview() {
  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {[1, 2, 3].map((item) => (
        <div key={item} className="rounded-[20px] border border-white/10 bg-[#0D131C] p-4">
          <p className="text-sm font-semibold text-white">Responsive sample {item}</p>
          <p className="mt-2 text-sm leading-7 text-zinc-400">The layout compresses cleanly from mobile to desktop without breaking hierarchy.</p>
        </div>
      ))}
    </div>
  );
}

function DarkModeValidation() {
  return (
    <div className="rounded-[24px] border border-white/10 bg-[#0B1119] p-5">
      <div className="rounded-[20px] border border-white/10 bg-[#111827] p-4">
        <p className="text-sm font-semibold text-white">Dark mode validation</p>
        <p className="mt-2 text-sm leading-7 text-zinc-400">Contrast, border, and surface treatments remain legible in dark environments.</p>
      </div>
    </div>
  );
}

export {
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
  SiaDangerButton,
  SiaGhostButton,
  SiaIconButton,
  SiaPrimaryButton,
  SiaSecondaryButton,
  SpacingScale,
  SportsIntelligenceScoreDisplay,
  TokenSwatch,
  TypographySample,
};

export default function DesignSystemComponents() {
  return null;
}
