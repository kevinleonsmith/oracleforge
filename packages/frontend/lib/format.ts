// Pure formatting helpers (no imports) — unit-tested with `node --test`.

/** basis points (0..10000) -> whole-percent integer. */
export function bpsToPercent(bps: number): number {
  return Math.round(bps / 100);
}

/** uint256 base-unit string -> number of whole tokens (display precision). */
export function formatUnits(base: string, decimals: number): number {
  if (!base) return 0;
  const neg = base.startsWith("-");
  const n = BigInt(neg ? base.slice(1) : base);
  const d = 10n ** BigInt(decimals);
  const whole = n / d;
  const frac = n % d;
  const val = Number(whole) + Number(frac) / Number(d);
  return neg ? -val : val;
}

/** Compact USD-style label, e.g. 48700000 -> "$48.7M". */
export function formatCompact(n: number, prefix = "$"): string {
  if (n >= 1_000_000) return `${prefix}${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${prefix}${(n / 1_000).toFixed(1)}K`;
  return `${prefix}${n.toFixed(0)}`;
}

/** Parimutuel implied YES odds from pool sizes (percent). */
export function impliedYesPercent(yesPool: string, noPool: string): number {
  const y = Number(BigInt(yesPool || "0"));
  const no = Number(BigInt(noPool || "0"));
  const total = y + no;
  if (total === 0) return 50;
  return Math.round((y / total) * 100);
}

export interface PayoutPreview {
  payout: number; // stake returned + winnings if the side wins
  profit: number; // winnings only
  roi: number; // profit / stake, percent
  pricePct: number; // implied probability of the chosen side after the stake, percent
}

/**
 * Parimutuel payout preview for a prospective position. Winners get their stake
 * back plus a pro-rata share of the (fee-reduced) losing pool — the same math
 * `MarketEngine.claim` settles with (fee default 2%).
 */
export function payoutPreview(
  yesPool: number,
  noPool: number,
  side: "YES" | "NO",
  stake: number,
  fee = 0.02
): PayoutPreview {
  const sidePool = side === "YES" ? yesPool : noPool;
  const otherPool = side === "YES" ? noPool : yesPool;
  if (stake <= 0) {
    const t = yesPool + noPool;
    return { payout: 0, profit: 0, roi: 0, pricePct: t ? (sidePool / t) * 100 : 50 };
  }
  const winnings = (stake / (sidePool + stake)) * otherPool * (1 - fee);
  return {
    payout: stake + winnings,
    profit: winnings,
    roi: (winnings / stake) * 100,
    pricePct: ((sidePool + stake) / (yesPool + noPool + stake)) * 100,
  };
}
