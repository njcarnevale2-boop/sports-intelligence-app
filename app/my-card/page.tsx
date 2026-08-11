"use client";

import { useEffect, useState } from "react";

import MyCardShell from "@/components/my-card-shell";
import { fetchJson } from "../lib/api";
import { trackAnalyticsEvent } from "../lib/analytics";
import type { SavedBet } from "@/lib/my-card-helpers";

type PortfolioBet = {
  id: string;
  eventId: string;
  commenceTime: string;
  matchup: string;
  awayTeam: string;
  homeTeam: string;
  pick: string;
  book: string;
  market: string;
  side: string;
  point: number;
  price: number;
  modelProbability: number;
  impliedProbability: number;
  fairOdds: number;
  edge: number;
  evPerDollar: number;
  kellyFull: number;
  kelly20: number;
  recommendation: string;
  rawUnits: number;
  recommendedUnits: number;
};

type PortfolioResponse = {
  count: number;
  source: string;
  summary: {
    totalRecommendedUnits: number;
    averageEdge: number;
    averageModelProbability: number;
    expectedValueUnits: number;
  };
  portfolio: PortfolioBet[];
};

export default function MyCardPage() {
  const [savedBets, setSavedBets] = useState<SavedBet[]>([]);

  useEffect(() => {
    void trackAnalyticsEvent("MyCardViewed", { page: "my-card" });

    const saved = localStorage.getItem("sports-intelligence-card");

    if (!saved) return;

    try {
      const parsed = JSON.parse(saved) as SavedBet[];
      setSavedBets(parsed);
    } catch (err) {
      console.error("Unable to read saved card:", err);
    }
  }, []);

  useEffect(() => {
    async function loadPortfolio() {
      try {
        const data = await fetchJson<PortfolioResponse>("/api/portfolio");
        const portfolio = data.portfolio.map((bet) => ({
          ...bet,
          id: bet.id,
          matchup: bet.matchup,
          pick: bet.pick,
          book: bet.book,
          edge: bet.edge,
          evPerDollar: bet.evPerDollar,
          kelly20: bet.kelly20,
          recommendation: bet.recommendation,
          confidence: bet.modelProbability,
          sportsIntelligenceScore: { score: Math.round(bet.edge + bet.modelProbability) },
          marketIntelligence: { score: Math.round((bet.edge + bet.modelProbability) / 2) },
          injuryContext: { summary: "Model view is neutral", awayInjuryScore: 15, homeInjuryScore: 12 },
        })) as SavedBet[];

        setSavedBets((current) => (current.length > 0 ? current : portfolio));
      } catch (err) {
        console.error(err);
      }
    }

    loadPortfolio();
  }, []);

  return <MyCardShell initialBets={savedBets} />;
}