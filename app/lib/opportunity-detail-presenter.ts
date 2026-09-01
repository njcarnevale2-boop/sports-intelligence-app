type PresenterMarket = {
  score: number;
};

type PresenterScore = {
  score: number;
  recommendation: string;
};

type PresenterOpportunity = {
  pick: string;
  point: number;
  price: number;
  book: string;
  modelProbability: number;
  impliedProbability: number;
  edge: number;
  evPerDollar: number;
  confidence: number;
  dataCompleteness: number;
  awayTeam: string;
  homeTeam: string;
  marketIntelligence: {
    score: number;
    consensus: number;
  };
  injuryContext?: {
    severity?: string | null;
  } | null;
  recommendedPlayableTo?: number | null;
  recommendedPlayableToStatus?: "AVAILABLE" | "UNAVAILABLE";
  truePlayableTo?: number | null;
  truePlayableToStatus?: "AVAILABLE" | "UNAVAILABLE";
};

type PresenterProjection = {
  awayTeam: string;
  homeTeam: string;
  model: {
    marginHome: number;
    projectedScore: {
      away: number;
      home: number;
    };
  };
  market: {
    homeSpread: number;
  };
  spreadAnalysis?: {
    edgePoints?: number;
  };
};

function formatOdds(price: number) {
  return price > 0 ? `+${price}` : `${price}`;
}

function formatLine(point: number) {
  return point > 0 ? `+${point}` : `${point}`;
}

function marketSpreadText(homeTeam: string, awayTeam: string, homeSpread: number) {
  if (Math.abs(homeSpread) < 0.0001) return "a pick'em";
  if (homeSpread < 0) return `${homeTeam} favored by ${Math.abs(homeSpread).toFixed(1)}`;
  return `${awayTeam} favored by ${Math.abs(homeSpread).toFixed(1)}`;
}

export function getMarketConfirmationLabel(score: number) {
  if (score >= 7) return "Strong";
  if (score >= 5) return "Mixed";
  return "Weak";
}

export function shouldShowMarketDisagreementExplanation(recommendation: string, marketScore: number) {
  const rec = recommendation.toUpperCase();
  const isBetRecommendation =
    rec.includes("BET") && !rec.includes("PASS") && !rec.includes("NO BET");
  return isBetRecommendation && marketScore < 5;
}

export function buildPrimaryWhySia(
  opp: PresenterOpportunity,
  projection: PresenterProjection | null,
  marketConfirmation: string
) {
  const pickTeam = opp.pick.split(" ")[0];

  const modelOutcome = projection
    ? `SIA projects ${projection.awayTeam} ${projection.model.projectedScore.away.toFixed(1)}-${projection.homeTeam} ${projection.model.projectedScore.home.toFixed(1)}.`
    : `SIA gives ${pickTeam} a ${opp.modelProbability.toFixed(1)}% win probability.`;

  const marketView = projection
    ? `The market currently has ${marketSpreadText(projection.homeTeam, projection.awayTeam, projection.market.homeSpread)}.`
    : `The market implies ${opp.impliedProbability.toFixed(1)}% at the current price.`;

  const canonicalSpreadDisagreement =
    projection?.spreadAnalysis?.edgePoints != null && Number.isFinite(projection.spreadAnalysis.edgePoints)
      ? Math.abs(projection.spreadAnalysis.edgePoints)
      : null;

  const disagreement = projection
    ? canonicalSpreadDisagreement != null
      ? `That is a ${canonicalSpreadDisagreement.toFixed(1)}-point disagreement versus the current spread, creating a ${opp.edge.toFixed(1)}-point model edge on ${opp.pick}.`
      : `That creates a ${opp.edge.toFixed(1)}-point model edge on ${opp.pick}.`
    : `That creates a ${opp.edge.toFixed(1)}-point model edge on ${opp.pick}.`;

  const value = opp.evPerDollar >= 0.08
    ? `At ${formatOdds(opp.price)}, expected value remains ${opp.evPerDollar >= 0.2 ? "strong" : "positive"} at +$${opp.evPerDollar.toFixed(3)} per dollar risked.`
    : `Expected value at ${formatOdds(opp.price)} is currently limited (+$${opp.evPerDollar.toFixed(3)} per dollar risked).`;

  const confirmation =
    marketConfirmation === "Strong"
      ? "Sportsbooks are confirming the model's direction."
      : marketConfirmation === "Mixed"
      ? "Sportsbook movement is mixed, so confirmation is still developing."
      : "Sportsbooks have not yet strongly confirmed the model's view.";

  return `${modelOutcome} ${marketView} ${disagreement} ${value} ${confirmation}`;
}

export function buildDecisionBoxes(
  opp: PresenterOpportunity,
  weatherStatus: { dataStatus?: string } | null
) {
  const whyBetIt: string[] = [];
  const whatCouldGoWrong: string[] = [];
  const whatToWatch: string[] = [];

  if (opp.edge >= 12) whyBetIt.push("Large model-vs-market disagreement");
  else if (opp.edge >= 5) whyBetIt.push("Positive model-vs-market disagreement");

  if (opp.evPerDollar >= 0.2) whyBetIt.push("Strong expected value at the current price");
  else if (opp.evPerDollar >= 0.08) whyBetIt.push("Positive expected value at the current price");

  if (opp.confidence >= 80) whyBetIt.push("High model confidence");
  if (opp.dataCompleteness >= 85) whyBetIt.push("Strong underlying data coverage");

  const injurySeverity = opp.injuryContext?.severity?.toLowerCase() ?? "neutral";
  if (injurySeverity === "neutral" || injurySeverity === "small") {
    whyBetIt.push("No material injury concern");
  }

  if (opp.marketIntelligence.score < 5) {
    whatCouldGoWrong.push("Sportsbooks have not strongly confirmed the model");
  } else if (opp.marketIntelligence.score < 7) {
    whatCouldGoWrong.push("Sportsbook confirmation is mixed");
  }

  if (injurySeverity === "moderate") {
    whatCouldGoWrong.push("Injury uncertainty is a moderate concern");
  }
  if (injurySeverity === "significant" || injurySeverity === "major") {
    whatCouldGoWrong.push("Injury uncertainty is a material concern");
  }
  if (opp.dataCompleteness < 70) {
    whatCouldGoWrong.push("Incomplete supporting data reduces conviction");
  }
  if (weatherStatus?.dataStatus === "UNAVAILABLE") {
    whatCouldGoWrong.push("Game-time weather context is not yet available");
  }
  if (whatCouldGoWrong.length === 0) {
    whatCouldGoWrong.push("No material risk signal is currently elevated");
  }

  whatToWatch.push("Line movement before kickoff");
  if (opp.injuryContext) {
    whatToWatch.push("Material injury/news changes before kickoff");
  }

  if (opp.truePlayableToStatus === "AVAILABLE" && opp.truePlayableTo != null) {
    const team = opp.pick.split(" ")[0];
    const playableTo = `${team} ${formatLine(opp.truePlayableTo)}`;
    whatToWatch.push(`Whether the best line deteriorates toward ${playableTo}`);
  } else {
    whatToWatch.push("Whether the best available line deteriorates toward SIA's playable boundary");
  }

  return {
    whyBetIt: whyBetIt.slice(0, 4),
    whatCouldGoWrong: whatCouldGoWrong.slice(0, 4),
    whatToWatch: whatToWatch.slice(0, 4),
  };
}

export function buildPrimaryDecisionSnapshot(
  opp: PresenterOpportunity,
  score: PresenterScore,
  stakeRecommendation: string,
  marketConfirmation: string
) {
  const line = `${opp.pick}`;
  const team = opp.pick.split(" ")[0] || "Selection";
  const recommendedBoundaryValue = opp.recommendedPlayableTo;
  const hasRecommendedBoundary =
    recommendedBoundaryValue != null && Number.isFinite(recommendedBoundaryValue);
  const theoreticalModelBoundary =
    hasRecommendedBoundary
      ? `${team} ${formatLine(recommendedBoundaryValue)}`
      : "See Game Intelligence";

  const mathematicalBoundaryValue = opp.truePlayableTo;
  const hasMathematicalBoundary =
    mathematicalBoundaryValue != null && Number.isFinite(mathematicalBoundaryValue);
  const mathematicalBoundary = hasMathematicalBoundary
    ? `${team} ${formatLine(mathematicalBoundaryValue)}`
    : "Unavailable";

  return {
    betLinePrice: `${line} (${formatOdds(opp.price)})`,
    recommendation: score.recommendation.toUpperCase(),
    siScore: score.score,
    siaWinProbability: opp.modelProbability,
    marketImpliedProbability: opp.impliedProbability,
    bestSportsbook: opp.book,
    line,
    price: formatOdds(opp.price),
    theoreticalModelBoundary,
    mathematicalBoundary,
    boundaryExplanation:
      "Research estimate only: this boundary assumes hypothetical pricing and is not an execution recommendation.",
    stakeRecommendation,
    marketConfirmation,
  };
}
