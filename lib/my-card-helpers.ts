export type SavedBet = {
  id?: string;
  eventId?: string;
  matchup: string;
  awayTeam?: string;
  homeTeam?: string;
  pick: string;
  book: string;
  market?: string;
  commenceTime?: string;
  point?: number;
  price?: number;
  confidence?: number;
  edge: number | string;
  evPerDollar?: number;
  kelly20?: number;
  recommendation?: string;
  sportsIntelligenceScore?: { score?: number };
  marketIntelligence?: { score?: number };
  injuryContext?: { summary?: string; awayInjuryScore?: number; homeInjuryScore?: number };
  alternateBooks?: Array<{ book: string; point: number; price: number; edge: number; evPerDollar: number }>;
};

export type CardSummary = {
  totalBets: number;
  averageSiScore: number;
  totalExpectedValue: number;
  recommendedBankrollExposure: number;
  portfolioRisk: string;
  averageEdge: number;
};

export type RiskWarning = {
  title: string;
  message: string;
  severity: 'warning' | 'danger';
};

export function normalizeSavedBet(bet: Record<string, unknown> & Partial<SavedBet>): SavedBet {
  return {
    id: typeof bet.id === 'string' ? bet.id : undefined,
    eventId: typeof bet.eventId === 'string' ? bet.eventId : undefined,
    matchup: typeof bet.matchup === 'string' ? bet.matchup : 'Unknown matchup',
    awayTeam: typeof bet.awayTeam === 'string' ? bet.awayTeam : undefined,
    homeTeam: typeof bet.homeTeam === 'string' ? bet.homeTeam : undefined,
    pick: typeof bet.pick === 'string' ? bet.pick : 'Market edge',
    book: typeof bet.book === 'string' ? bet.book : 'Primary sportsbook',
    market: typeof bet.market === 'string' ? bet.market : undefined,
    commenceTime: typeof bet.commenceTime === 'string' ? bet.commenceTime : undefined,
    point: typeof bet.point === 'number' ? bet.point : undefined,
    price: typeof bet.price === 'number' ? bet.price : undefined,
    confidence: typeof bet.confidence === 'number' ? bet.confidence : undefined,
    edge: typeof bet.edge === 'number' ? bet.edge : String(bet.edge ?? '0%'),
    evPerDollar: typeof bet.evPerDollar === 'number' ? bet.evPerDollar : undefined,
    kelly20: typeof bet.kelly20 === 'number' ? bet.kelly20 : undefined,
    recommendation: typeof bet.recommendation === 'string' ? bet.recommendation : undefined,
    sportsIntelligenceScore: typeof bet.sportsIntelligenceScore === 'object' && bet.sportsIntelligenceScore ? bet.sportsIntelligenceScore as { score?: number } : undefined,
    marketIntelligence: typeof bet.marketIntelligence === 'object' && bet.marketIntelligence ? bet.marketIntelligence as { score?: number } : undefined,
    injuryContext: typeof bet.injuryContext === 'object' && bet.injuryContext ? bet.injuryContext as { summary?: string; awayInjuryScore?: number; homeInjuryScore?: number } : undefined,
    alternateBooks: Array.isArray(bet.alternateBooks) ? bet.alternateBooks as Array<{ book: string; point: number; price: number; edge: number; evPerDollar: number }> : undefined,
  };
}

export function getEdgeValue(edge: SavedBet['edge']): number {
  if (typeof edge === 'number') return edge;
  if (typeof edge === 'string') {
    const cleaned = edge.replace('%', '').replace('+', '').trim();
    const numeric = Number.parseFloat(cleaned);
    return Number.isFinite(numeric) ? numeric : 0;
  }
  return 0;
}

export function buildCardSummary(bets: SavedBet[]): CardSummary {
  if (bets.length === 0) {
    return {
      totalBets: 0,
      averageSiScore: 0,
      totalExpectedValue: 0,
      recommendedBankrollExposure: 0,
      portfolioRisk: 'Neutral',
      averageEdge: 0,
    };
  }

  const averageSiScore = bets.reduce((sum, bet) => sum + (bet.sportsIntelligenceScore?.score ?? 0), 0) / bets.length;
  const totalExpectedValue = bets.reduce((sum, bet) => sum + (bet.evPerDollar ?? 0), 0);
  const recommendedBankrollExposure = bets.reduce((sum, bet) => sum + (bet.kelly20 ?? 0), 0);
  const averageEdge = bets.reduce((sum, bet) => sum + getEdgeValue(bet.edge), 0) / bets.length;

  let portfolioRisk = 'Balanced';
  if (recommendedBankrollExposure > 2.5) portfolioRisk = 'High';
  else if (recommendedBankrollExposure > 1.2) portfolioRisk = 'Moderate';

  return {
    totalBets: bets.length,
    averageSiScore: Number(averageSiScore.toFixed(1)),
    totalExpectedValue: Number(totalExpectedValue.toFixed(2)),
    recommendedBankrollExposure: Number(recommendedBankrollExposure.toFixed(2)),
    portfolioRisk,
    averageEdge: Number(averageEdge.toFixed(2)),
  };
}

export function buildPortfolioRiskWarnings(bets: SavedBet[]): RiskWarning[] {
  const warnings: RiskWarning[] = [];
  const teamCounts = new Map<string, number>();
  const gameCounts = new Map<string, number>();
  const bankrollExposure = bets.reduce((sum, bet) => sum + (bet.kelly20 ?? 0), 0);

  bets.forEach((bet) => {
    const teamKey = bet.awayTeam || bet.matchup;
    teamCounts.set(teamKey, (teamCounts.get(teamKey) || 0) + 1);
    if (bet.eventId) {
      gameCounts.set(bet.eventId, (gameCounts.get(bet.eventId) || 0) + 1);
    }
  });

  if (bets.length >= 3) {
    warnings.push({
      title: 'Correlated exposure',
      message: 'Your card includes several correlated positions that may amplify shared risk.',
      severity: 'warning',
    });
  }

  if (bets.length >= 3 && bets.filter((bet) => (bet.kelly20 ?? 0) > 0.5).length >= 3) {
    warnings.push({
      title: 'Bankroll concentration',
      message: 'Recommended bankroll exposure is above the suggested risk range for a single card.',
      severity: 'danger',
    });
  }

  if (bankrollExposure > 2.5) {
    warnings.push({
      title: 'Bankroll concentration',
      message: 'Recommended bankroll exposure is above the suggested risk range for a single card.',
      severity: 'danger',
    });
  }

  if (Array.from(teamCounts.values()).some((count) => count >= 2)) {
    warnings.push({
      title: 'Single-team concentration',
      message: 'Multiple selections are tied to the same team, increasing event risk.',
      severity: 'warning',
    });
  }

  if (Array.from(gameCounts.values()).some((count) => count >= 2)) {
    warnings.push({
      title: 'Single-game concentration',
      message: 'More than one selection in the same game can create heavy variance.',
      severity: 'warning',
    });
  }

  return warnings;
}

export function createExportPayload(bets: SavedBet[]) {
  return {
    generatedAt: new Date().toISOString(),
    bets,
  };
}
