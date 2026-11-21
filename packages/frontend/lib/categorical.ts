// Categorical (N-outcome) market math — the UI mirror of CategoricalMarketEngine's
// winner-take-all settlement. No imports, no network: unit-tested with `node --test`.
//
// A categorical market has N mutually-exclusive outcomes, each with its own pool.
// At settlement the oracle names the single winning outcome; its pool takes the
// entire losing pot, minus the fee, pro-rata to stake:
//   winningPool = pools[w],  losingPool = totalPot - winningPool
//   fee         = losingPool * feeBps / 10_000      (snapshotted at creation; default 2%)
//   payout(a)   = stake(a) + stake(a) * (losingPool - fee) / winningPool
// A binary market is the N = 2 case. See docs/CATEGORICAL-MARKETS.md.

export interface CategoricalOutcome {
  label: string;
  pool: number;
}

/**
 * Implied probability of each outcome, as a fraction in [0, 1] summing to 1 —
 * each pool's share of the total pot (what the book prices in). An empty book
 * falls back to a uniform split so the bars still render.
 */
export function impliedProbabilities(outcomes: CategoricalOutcome[]): number[] {
  const n = outcomes.length;
  if (n === 0) return [];
  const pot = outcomes.reduce((a, o) => a + o.pool, 0);
  if (pot <= 0) return outcomes.map(() => 1 / n);
  return outcomes.map((o) => o.pool / pot);
}

export interface CategoricalPreview {
  payout: number; // stake returned + winnings if `outcome` wins
  profit: number; // payout - stake
  roi: number; // profit / stake, percent
  impliedProb: number; // the chosen outcome's implied probability, 0..1
  voids: boolean; // true if staking here would be the only funded outcome (no losing pot) — a push
}

/**
 * Payout for a prospective stake on `outcome` if that outcome wins. Mirrors the
 * contract: the stake joins its pool (winningPool = pools[w] + stake), the fee is
 * skimmed from the losing pot, and the winning pool splits the rest pro-rata. The
 * stake's own contribution cancels out of the losing pool, so a bigger self-stake
 * only dilutes the per-unit winnings — exactly as on-chain.
 *
 * If the chosen outcome would be the *only* funded one, there is no losing pot:
 * the market voids (push) and the stake is simply returned (`voids: true`).
 */
export function categoricalPayoutPreview(
  outcomes: CategoricalOutcome[],
  outcome: number,
  stake: number,
  fee = 0.02
): CategoricalPreview {
  const probs = impliedProbabilities(outcomes);
  const impliedProb = probs[outcome] ?? 0;
  if (stake <= 0 || outcome < 0 || outcome >= outcomes.length) {
    return { payout: 0, profit: 0, roi: 0, impliedProb, voids: false };
  }

  const totalPot = outcomes.reduce((a, o) => a + o.pool, 0);
  const losingPool = totalPot - outcomes[outcome].pool; // unaffected by the self-stake
  const winningPool = outcomes[outcome].pool + stake;

  // No losing pot -> void/push: principal back, no winnings, no fee.
  if (losingPool <= 0) {
    return { payout: stake, profit: 0, roi: 0, impliedProb, voids: true };
  }

  const distributable = losingPool * (1 - fee);
  const payout = stake + (stake * distributable) / winningPool;
  return { payout, profit: payout - stake, roi: (payout / stake - 1) * 100, impliedProb, voids: false };
}

/** Index of the current front-runner (largest pool); -1 for an empty book. */
export function favorite(outcomes: CategoricalOutcome[]): number {
  let best = -1;
  let bestPool = 0;
  outcomes.forEach((o, i) => {
    if (o.pool > bestPool) {
      bestPool = o.pool;
      best = i;
    }
  });
  return best;
}
