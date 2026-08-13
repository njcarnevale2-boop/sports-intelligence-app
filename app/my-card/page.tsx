"use client";

import { useCallback, useEffect, useState } from "react";

import MyCardShell from "@/components/my-card-shell";
import { fetchJson } from "../lib/api";
import { trackAnalyticsEvent } from "../lib/analytics";
import { normalizeSavedBet, type SavedBet } from "@/lib/my-card-helpers";

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

const CARD_KEY = "sports-intelligence-card";

export default function MyCardPage() {
  const [bets, setBets] = useState<SavedBet[]>([]);

  // Owned here so CLV enrichment and removals share a single state reference
  const removeBet = useCallback((idOrEventId: string) => {
    setBets((current) => {
      const updated = current.filter(
        (b) => b.id !== idOrEventId && b.eventId !== idOrEventId
      );
      try {
        localStorage.setItem(CARD_KEY, JSON.stringify(updated));
      } catch { /* storage unavailable */ }
      return updated;
    });
  }, []);

  useEffect(() => {
    void trackAnalyticsEvent("MyCardViewed", { page: "my-card" });

    const saved = localStorage.getItem(CARD_KEY);
    if (!saved) return;

    try {
      const parsed = JSON.parse(saved) as Array<Record<string, unknown>>;
      // Drop legacy bets (no eventId AND no awayTeam/homeTeam) written by old hardcoded stub
      const valid = parsed.filter((raw) => raw.eventId || (raw.awayTeam && raw.homeTeam));
      if (valid.length < parsed.length) {
        try { localStorage.setItem(CARD_KEY, JSON.stringify(valid)); } catch { /* storage unavailable */ }
      }
      const normalized = valid.map(normalizeSavedBet);
      setBets(normalized);
      // Functional updater: only applies CLV to bets still on the card
      void enrichWithClv(normalized).then((enriched) =>
        setBets((current) =>
          current.map((b) => {
            const e = enriched.find(
              (r) => (b.id && r.id === b.id) || (b.eventId && r.eventId === b.eventId)
            );
            return e ?? b;
          })
        )
      );
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

        setBets((current) => (current.length > 0 ? current : portfolio.map(normalizeSavedBet)));
      } catch (err) {
        console.error(err);
      }
    }

    loadPortfolio();
  }, []);

  return <MyCardShell bets={bets} onRemoveBet={removeBet} />;
}

async function enrichWithClv(bets: SavedBet[]): Promise<SavedBet[]> {
  return Promise.all(
    bets.map(async (bet) => {
      if (!bet.eventId) return bet;
      try {
        const resp = await fetchJson<{ records: Array<{ closingStatus: string; closingPoint: number | null; closingPrice: number | null; clvPoints: number | null; clvProbability: number | null; clvPercent: number | null }> }>(
          `/api/recommendation/clv/${bet.eventId}`
        );
        const first = resp.records?.[0];
        if (!first) return bet;
        return {
          ...bet,
          clv: {
            closingStatus: first.closingStatus,
            closingPoint: first.closingPoint,
            closingPrice: first.closingPrice,
            clvPoints: first.clvPoints,
            clvProbability: first.clvProbability,
            clvPercent: first.clvPercent,
          },
        };
      } catch {
        return bet;
      }
    })
  );
}