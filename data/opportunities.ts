export type Opportunity = {
  id: string;
  matchup: string;
  pick: string;
  book: string;
  confidence: number;
  edge: string;
  status: "Strong" | "Playable" | "Monitor";
  reason: string;
};

export const opportunities: Opportunity[] = [
  {
    id: "buffalo-ravens",
    matchup: "Bills @ Ravens",
    pick: "Buffalo +3",
    book: "FanDuel",
    confidence: 91,
    edge: "+6.8%",
    status: "Strong",
    reason:
      "The injury adjustment improved Buffalo's matchup and the current line remains above our fair number.",
  },
  {
    id: "detroit-packers",
    matchup: "Lions @ Packers",
    pick: "Detroit -2.5",
    book: "DraftKings",
    confidence: 86,
    edge: "+4.9%",
    status: "Playable",
    reason:
      "Model support remains strong, but market movement is beginning to reduce the available value.",
  },
  {
    id: "bengals-browns-under",
    matchup: "Bengals @ Browns",
    pick: "Under 44.5",
    book: "Caesars",
    confidence: 82,
    edge: "+3.7%",
    status: "Monitor",
    reason:
      "Weather and expected pace support the under, but injury uncertainty keeps this below our strongest tier.",
  },
];