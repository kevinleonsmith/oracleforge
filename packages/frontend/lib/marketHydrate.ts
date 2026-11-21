// Pure helpers that merge a live on-chain read (base-unit pools) into a scalar or
// categorical market's UI shape. No imports with side effects, no network — so the
// mapping is unit-tested with `node --test`. The chain client (chainApi) reads the
// engine, then calls these to refresh the pools the panels display; the mock client
// returns the defs untouched.
import type { ScalarMarketData } from "@/components/ScalarMarketCard";
import type { CategoricalMarketData } from "@/components/CategoricalMarketCard";
import type { OnchainScalarMarket, OnchainCategoricalMarket } from "./marketDecode";

/**
 * Convert a base-unit amount (wei-like string/bigint) to whole token units for
 * display. Precision beyond Number is irrelevant for a pool label, so a Number
 * divide is fine; a malformed input reads as 0.
 */
export function baseUnitsToTokens(raw: string | bigint, decimals: number): number {
  let v: bigint;
  try {
    v = typeof raw === "bigint" ? raw : BigInt(raw || "0");
  } catch {
    return 0;
  }
  return Number(v) / 10 ** decimals;
}

/**
 * Refresh a scalar market def's LONG/SHORT pools from its on-chain state, leaving
 * the band, unit and labels (which come from market creation, not stored per-read)
 * as defined. A null read leaves the def untouched.
 */
export function hydrateScalar(
  def: ScalarMarketData,
  live: OnchainScalarMarket | null,
  decimals: number
): ScalarMarketData {
  if (!live) return def;
  return {
    ...def,
    longPool: baseUnitsToTokens(live.longPool, decimals),
    shortPool: baseUnitsToTokens(live.shortPool, decimals),
  };
}

/**
 * Refresh a categorical market def's per-outcome pools from its on-chain state,
 * matched by index and keeping each outcome's label. Outcomes the chain read does
 * not cover (shorter pools array) keep their def value. A null read is a no-op.
 */
export function hydrateCategorical(
  def: CategoricalMarketData,
  live: OnchainCategoricalMarket | null,
  decimals: number
): CategoricalMarketData {
  if (!live) return def;
  return {
    ...def,
    outcomes: def.outcomes.map((o, i) =>
      i < live.pools.length ? { ...o, pool: baseUnitsToTokens(live.pools[i], decimals) } : o
    ),
  };
}
