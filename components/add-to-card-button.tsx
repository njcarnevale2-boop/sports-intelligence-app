"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";

const bet = {
  matchup: "Bills @ Ravens",
  pick: "Buffalo +3",
  book: "FanDuel",
  confidence: 91,
  edge: "+6.8%",
};

export default function AddToCardButton() {
  const [added, setAdded] = useState(false);

  function addToCard() {
    localStorage.setItem(
      "sports-intelligence-card",
      JSON.stringify([bet])
    );

    setAdded(true);
  }

  if (added) {
    return (
      <Link href="/my-card">
        <Button
          variant="outline"
          className="h-11 border-emerald-400/30 bg-emerald-400/10 px-5 text-emerald-300 hover:bg-emerald-400/15"
        >
          Added ✓ View My Card
        </Button>
      </Link>
    );
  }

  return (
    <Button
      onClick={addToCard}
      variant="outline"
      className="h-11 border-white/10 bg-transparent px-5 text-white hover:bg-white/[0.05]"
    >
      Add to My Card
    </Button>
  );
}