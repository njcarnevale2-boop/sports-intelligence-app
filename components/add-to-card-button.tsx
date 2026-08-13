"use client";

import { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { addToCard, type SavedCardItem } from "@/lib/add-to-card";

type Props = {
  opportunity: SavedCardItem;
};

export default function AddToCardButton({ opportunity }: Props) {
  const [added, setAdded] = useState(false);
  const [loading, setLoading] = useState(false);

  async function handleAdd() {
    if (added || loading) return;
    setLoading(true);
    await addToCard(opportunity);
    setLoading(false);
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
      onClick={() => void handleAdd()}
      disabled={loading}
      variant="outline"
      className="h-11 border-white/10 bg-transparent px-5 text-white hover:bg-white/[0.05]"
    >
      {loading ? "Adding…" : "Add to My Card"}
    </Button>
  );
}
