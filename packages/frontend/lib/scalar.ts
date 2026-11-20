// Scalar (range) market math — the UI mirror of ScalarMarketEngine's settlement.
// No imports, no network: unit-tested with `node --test`.
//
// A scalar market has a band [lower, upper]; traders take LONG or SHORT. At
// settlement the oracle value is clamped into the band to a fraction
//   f = (clamp(v) - lower) / (upper - lower)   in [0, 1]
// and the pot (minus fee) is split: LONG gets f, SHORT gets (1 - f), each trader
// pro-rata within their side. See docs/SCALAR-MARKETS.md.

export type ScalarSide = "LONG" | "SHORT";

/** Settlement fraction for a value, clamped into [0, 1]. */
export function settlementFraction(lower: number, upper: number, value: number): number {
  if (upper <= lower) return 0;
  const f = (value - lower) / (upper - lower);
  return f < 0 ? 0 : f > 1 ? 1 : f;
}

/**
 * The value the current book prices in. A risk-neutral LONG breaks even when the
 * settlement fraction equals the LONG pool's share of the pot (f = longPool/pot),
 * so the implied settlement point is `lower + (longPool/pot) * (upper - lower)`.
 * Falls back to the band midpoint for an empty book.
 */
export function impliedValue(
  lower: number,
  upper: number,
  longPool: number,
  shortPool: number
): number {
  const pot = longPool + shortPool;
  const f = pot > 0 ? longPool / pot : 0.5;
  return lower + f * (upper - lower);
}

export interface ScalarPreview {
  payout: number; // stake returned + winnings (or less) if it settles at `atValue`
  profit: number; // payout - stake (can be negative: scalar lets you lose part of the stake)
  roi: number; // profit / stake, percent
  fraction: number; // the settlement fraction at `atValue`, 0..1
}

/**
 * Payout for a prospective LONG/SHORT stake if the market settles at `atValue`.
 * Mirrors the contract: the stake joins its side's pool, the fee is skimmed from
 * the whole pot, and the side's share (f for LONG, 1-f for SHORT) is split
 * pro-rata within the side.
 */
export function scalarPayoutPreview(
  lower: number,
  upper: number,
  longPool: number,
  shortPool: number,
  side: ScalarSide,
  stake: number,
  atValue: number,
  fee = 0.02
): ScalarPreview {
  const fraction = settlementFraction(lower, upper, atValue);
  if (stake <= 0) return { payout: 0, profit: 0, roi: 0, fraction };

  const isLong = side === "LONG";
  const sidePool = (isLong ? longPool : shortPool) + stake;
  const pot = longPool + shortPool + stake;
  const distributable = pot * (1 - fee);
  const sideShare = distributable * (isLong ? fraction : 1 - fraction);
  const payout = (sideShare * stake) / sidePool;

  return { payout, profit: payout - stake, roi: (payout / stake - 1) * 100, fraction };
}

/** Where the implied value sits on the band, as a 0..100 percentage (for a marker). */
export function bandPercent(lower: number, upper: number, value: number): number {
  return Math.round(settlementFraction(lower, upper, value) * 100);
}
