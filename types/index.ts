export type ConfidenceLevel = "low" | "medium" | "high";

export type Opportunity = {
  id: string;
  matchup: string;
  market: string;
  line: string;
  confidence: number;
  edge: number;
  risk: ConfidenceLevel;
};

export type IntelligenceUpdate = {
  id: string;
  type: "injury" | "weather" | "market" | "fantasy";
  title: string;
  summary: string;
  impact: string;
};