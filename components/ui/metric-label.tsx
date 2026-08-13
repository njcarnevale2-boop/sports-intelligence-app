"use client";

import Tooltip from "./tooltip";

/**
 * Renders a metric name with an inline ⓘ tooltip. Use inside <p> or <span>.
 * Example: <MetricLabel term="Model Edge" /> → "Model Edge ⓘ"
 * Override display text with the `label` prop when the visible label differs
 * from the glossary key (e.g. label="EV / $1" term="EV").
 */
export default function MetricLabel({
  term,
  label,
  className,
}: {
  term: string;
  label?: string;
  className?: string;
}) {
  return (
    <span className={`inline-flex items-center${className ? ` ${className}` : ""}`}>
      {label ?? term}
      <Tooltip term={term} />
    </span>
  );
}
