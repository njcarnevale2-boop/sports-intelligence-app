"use client";

import { useState, useRef, useEffect } from "react";
import { HelpCircle } from "lucide-react";

const GLOSSARY: Record<string, string> = {
  "SI Score":
    "Sports Intelligence Score — a 0–100 signal combining model edge, expected value, confidence, market intelligence, and data completeness. Higher is stronger.",
  "Model Edge":
    "How much better the model thinks your chances are versus the market's implied probability. +5% edge means the model estimates you have a 5% advantage over the posted price.",
  "Expected Value":
    "The average dollars you can expect to win per $1 risked over many similar bets, if the model is calibrated correctly. Positive EV bets are mathematically profitable long-term.",
  "Confidence":
    "How certain the model is about this projection, based on data quality, lineup completeness, and historical accuracy for this game type.",
  "Market Intelligence":
    "A signal derived from how multiple sportsbooks are pricing and moving the line. High market intelligence means sharp money or consensus movement supports the bet.",
  "Steam":
    "Rapid coordinated line movement across several books at once — typically a signal that sharp bettors have placed large wagers on one side.",
  "Kelly":
    "Kelly Criterion — a mathematical formula for sizing bets proportionally to your edge. The '20% Kelly' column uses a fractional version to reduce variance.",
  "CLV":
    "Closing Line Value — how your bet compares with the market's final price before kickoff. Positive CLV means you got a better number than what the market closed at.",
  "EV":
    "Expected Value — see 'Expected Value' above.",
  "Data Completeness":
    "What percentage of relevant context (lineups, injuries, weather, market data) is available for this game. Low completeness reduces model confidence.",
};

type GlossaryKey = keyof typeof GLOSSARY;

export { GLOSSARY };

export default function Tooltip({ term }: { term: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  const definition = GLOSSARY[term];
  if (!definition) return null;

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  return (
    <span ref={ref} className="relative inline-flex items-center">
      <button
        type="button"
        aria-label={`What is ${term}?`}
        onClick={() => setOpen((v) => !v)}
        className="ml-1 text-zinc-600 transition hover:text-zinc-300 focus:outline-none focus-visible:ring-1 focus-visible:ring-white/30"
      >
        <HelpCircle size={13} strokeWidth={1.8} />
      </button>

      {open && (
        <span
          role="tooltip"
          className="absolute block bottom-full left-1/2 z-50 mb-2 w-64 -translate-x-1/2 rounded-2xl border border-white/10 bg-[#0D141D] p-4 text-xs leading-5 text-zinc-300 shadow-2xl shadow-black/40"
        >
          <span className="block font-semibold text-white">{term}</span>
          <span className="mt-1 block text-zinc-400">{definition}</span>
          {/* Caret */}
          <span className="absolute block left-1/2 top-full -mt-px h-0 w-0 -translate-x-1/2 border-x-4 border-t-4 border-x-transparent border-t-[#0D141D]" />
        </span>
      )}
    </span>
  );
}
