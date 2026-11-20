// Shared UI types + helpers for the interactive terminal (client components).
import type { Market } from "@oracleforge/shared/types";

export interface UiMarket {
  id: string;
  category: string;
  question: string;
  yes: number; // YES pool (numeric, for the demo trade math)
  no: number; // NO pool
  aiProbBps: number;
}

export interface Position {
  id: string;
  question: string;
  side: "YES" | "NO";
  stake: number;
  payout: number;
}

export const CAT_COLOR: Record<string, string> = {
  MACRO: "var(--cyan)",
  CRYPTO: "var(--ember)",
  GEO: "var(--violet)",
  CLIMATE: "var(--green)",
};

export function toUiMarket(m: Market): UiMarket {
  return {
    id: m.marketId,
    category: m.category,
    question: m.question,
    yes: Number(m.yesPool || "0"),
    no: Number(m.noPool || "0"),
    aiProbBps: m.aiProbBps,
  };
}

export function catColor(category: string): string {
  return CAT_COLOR[category] ?? "var(--cyan)";
}
