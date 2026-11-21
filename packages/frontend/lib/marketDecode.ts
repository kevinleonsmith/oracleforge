// Pure decoders for the engines' getMarket tuples -> the UI's on-chain shape. No
// imports (no viem, no path aliases), so these are unit-tested with `node --test`;
// lib/contracts wraps them around the viem read and re-exports them.

export const STATUS = ["OPEN", "CLOSED", "RESOLVED", "INVALID"] as const;
export type MarketStatus = (typeof STATUS)[number];

export interface OnchainScalarMarket {
  status: MarketStatus;
  lower: string;
  upper: string;
  longPool: string;
  shortPool: string;
  settledValue?: string; // only meaningful once RESOLVED
}

/** Decode the scalar engine's getMarket tuple. Null for a nonexistent market. */
export function decodeScalarMarket(m: {
  createdAt: bigint; status: number; lower: bigint; upper: bigint;
  longPool: bigint; shortPool: bigint; settledValue: bigint;
}): OnchainScalarMarket | null {
  if (m.createdAt === 0n) return null;
  const status = STATUS[m.status] ?? "OPEN";
  return {
    status,
    lower: m.lower.toString(),
    upper: m.upper.toString(),
    longPool: m.longPool.toString(),
    shortPool: m.shortPool.toString(),
    settledValue: status === "RESOLVED" ? m.settledValue.toString() : undefined,
  };
}

export interface OnchainCategoricalMarket {
  status: MarketStatus;
  outcomeCount: number;
  pools: string[]; // per-outcome staked totals, base units
  winningOutcome?: number; // only meaningful once RESOLVED
}

/** Decode the categorical engine's getMarket tuple. Null for a nonexistent market. */
export function decodeCategoricalMarket(m: {
  createdAt: bigint; status: number; outcomeCount: number;
  winningOutcome: number; pools: readonly bigint[];
}): OnchainCategoricalMarket | null {
  if (m.createdAt === 0n) return null;
  const status = STATUS[m.status] ?? "OPEN";
  return {
    status,
    outcomeCount: Number(m.outcomeCount),
    pools: m.pools.map((p) => p.toString()),
    winningOutcome: status === "RESOLVED" ? Number(m.winningOutcome) : undefined,
  };
}
