"use client";

import { useState, useRef, useEffect } from "react";
import { HelpCircle } from "lucide-react";

const GLOSSARY: Record<string, string> = {
  "SI Score":
    "SIA's composite opportunity rating (0–100) weighted across model edge (30%), expected value (20%), confidence (15%), market intelligence (15%), data completeness (10%), and injury context (10%). Higher scores indicate stronger overall opportunities. A high SI Score does not guarantee a win.",
  "Model Probability":
    "SIA's estimated probability that the selected outcome occurs. Distinct from Confidence — Model Probability is the model's view of the true likelihood of the outcome, not a measure of how reliable the supporting data is.",
  "Market Implied":
    "The probability implied by the current sportsbook odds. For example, -110 odds imply approximately 52.4%. This reflects what the market currently prices the outcome at.",
  "Model Edge":
    "The gap between SIA's estimated probability and the market's implied probability. +8% edge means SIA estimates the outcome is 8 percentage points more likely than the posted odds imply. Positive edge suggests potential mispricing — it does not guarantee a win.",
  "Expected Value":
    "Estimated average return per $1 risked over many similar bets, calculated from SIA's probability estimate. Positive EV reflects mathematical value at the current price — individual outcomes still vary widely and a single win or loss proves nothing.",
  "EV":
    "Expected Value — estimated average return per $1 risked across many similar bets. Positive EV reflects mathematical value, not a guaranteed profit on any individual wager.",
  "Confidence":
    "How strongly SIA's signals support the prediction, based on data quality, signal consistency, and available context (0–100 scale). Confidence measures the quality of the evidence — it is NOT a win probability. A bet can have 90% Confidence and still lose.",
  "Kelly 20%":
    "A conservative bankroll-sizing guideline derived from the Kelly Criterion, capped at 20% of the full Kelly recommendation to limit volatility. This is a rough sizing signal — not financial advice. Actual stake decisions rest with you.",
  "Kelly":
    "Kelly Criterion — a mathematical formula for sizing bets in proportion to your estimated edge. SIA shows the '20% Kelly' figure, a conservative fractional version that limits variance compared to full Kelly.",
  "Fair Odds":
    "The sportsbook price that would correspond exactly to SIA's estimated probability. If fair odds are -120 and the posted price is -105, the bet carries positive expected value at the current market price.",
  "Steam":
    "Rapid, coordinated line movement across multiple sportsbooks in a short window — often interpreted as a signal that sharp or influential bettors have acted on one side. Steam does not guarantee a correct outcome.",
  "CLV":
    "Closing Line Value — the difference between the price captured when you added a bet and the market's final closing price before kickoff. Positive CLV means you received better odds than the market's closing consensus. CLV is widely used to assess long-term betting quality.",
  "Market Intelligence":
    "SIA's analysis of sportsbook pricing behavior, including how many books are moving, the magnitude of line moves, steam signals, and directional consensus. High Market Intelligence score means market data supports the model's position.",
  "Market Grade":
    "A letter grade (A–F) summarising how strongly sportsbook movement and market signals support the SIA recommendation. It is separate from the overall SI Score. A lower Market Grade means the broader market has not yet moved toward the model's position — this can reduce conviction, but a bet with a low Market Grade can still carry strong model edge and positive expected value.",
  "Data Completeness":
    "The percentage of relevant context available for this projection — including injury reports, weather data, and market information. Low completeness reduces model confidence in the assessment.",
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
