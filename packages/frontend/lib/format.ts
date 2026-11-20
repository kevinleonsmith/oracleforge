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
