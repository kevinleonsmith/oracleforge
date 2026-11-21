# OracleForge — Categorical (N-outcome) Markets

Binary markets answer yes/no; scalar markets answer a number. **Categorical
markets** answer *which one* — "who wins the election?", "which team takes the
title?" — across `N` mutually-exclusive outcomes. `CategoricalMarketEngine` is the
contract foundation; the binary `MarketEngine` and scalar `ScalarMarketEngine` are
unchanged and independent.

> MVP scaffold, not audited. Built with the same hardened posture as the other
> engines (two-step admin, zero-address guards, fee snapshotted at creation,
> no-winner void).

## The model

A market has `outcomeCount` outcomes indexed `0..N-1` (`2 <= N <= 64`). Each trader
stakes on exactly one. At settlement the oracle names the single **winning
outcome**, and the winning pool takes the entire losing pot, minus the fee,
pro-rata to stake — winner-take-all, exactly the binary engine generalized from 2
outcomes to N:

```
winningPool = pools[winner]
totalPot    = sum(pools)
losingPool  = totalPot - winningPool
fee         = losingPool * feeBps / 10_000      (snapshotted at creation; default 2%)
payout(a)   = stake(a) + stake(a) * (losingPool - fee) / winningPool
```

A **binary market is the `N = 2` case** (Yes/No): the winning side takes the whole
losing pool net of fee, identical to `MarketEngine`. A test pins this equivalence.

## Worked example

Three outcomes. Outcome 0: Alice 600 + Bob 400 (pool 1000). Outcome 1: Carol 500.
Outcome 2: Dave 500. Pot 2000. **Outcome 0 wins.**

```
winningPool = 1000,  losingPool = 1000,  fee = 2% * 1000 = 20,  distributable = 980
Alice = 600 + 600 * 980 / 1000 = 1188
Bob   = 400 + 400 * 980 / 1000 =  792
Carol, Dave        → nothing (claim reverts "no winnings")
```

Value is conserved: `1188 + 792 + 20 (fee) = 2000`.

## Edge cases & guarantees

- **No winner → void.** If nobody staked the winning outcome (`winningPool == 0`),
  the market **voids** (status `Invalid`) and every principal is refunded, no fee —
  claim needs `winningPool > 0` as the pro-rata denominator, and the losing pot
  would otherwise be stranded. The same push handling as the binary no-winner case.
- **Invalid / cancelled → void.** The oracle signals an invalid or cancelled event
  by returning an **out-of-range outcome** (`>= outcomeCount`, e.g. the sentinel
  `type(uint8).max`); the engine voids and refunds. One channel covers both "bad
  index" and "no result".
- **Value conservation** holds for any book and any winner:
  `sum(payouts) + fee + dust == deposits`, where `dust` is sub-wei floor-division
  rounding retained in the contract (bounded by the number of winning claimants).
  Proven by `testFuzz_conservesWithTwoWinners` and `testFuzz_conservesForAnyOutcomeCount`
  (variable `N`, arbitrary winner), 512 runs each.
- **Fee is snapshotted** at creation, so an admin can't change the economics of an
  in-flight market.
- **Bounded loops.** `N` is capped at `MAX_OUTCOMES = 64`, so the resolve-time pot
  sum and the void-refund loop stay gas-bounded; the invalid sentinel (255) is
  always above the cap, so it can never collide with a valid index.

## Oracle

Categorical settlement needs a winning *index*, not a yes/no or a number, so it
uses a separate `ICategoricalOracleAdapter`
(`latestOutcome(marketId) -> (ready, outcome)`). `MockCategoricalOracle` drives the
unit tests (`set` names the winner, `setInvalid` reports the void sentinel,
`clear` marks not-yet-ready).

## Optimistic resolution (opt-in)

Like the binary and scalar engines, settlement is optimistic when a nonzero
`challengeWindow` is set. `resolve()` then only **proposes** the oracle's winning
index (status `Closed`); anyone may `dispute()` within the window by posting
`disputeBond` collateral, which freezes the market until the admin `arbitrate()`s.
An upheld challenge refunds the bond and the admin's ruling becomes authoritative;
a rejected one forfeits the bond to the treasury and the proposed outcome stands.
Once the window passes with no open dispute, `finalize()` settles and opens claims.
A zero window keeps atomic settlement (v1 behavior), so the feature is opt-in and
additive. The exact bond is snapshotted per dispute, so changing the global
`disputeBond` mid-dispute can't mis-refund.

Unlike the scalar engine — whose one-sided-book void is *structural* and settles
immediately, bypassing the window — categorical's voids (an out-of-range/invalid
index, or a winning pool with no stake) depend on the *final* winning outcome, so
they are decided at **finalization**: a dispute can move the outcome to a funded
one, or an admin can deliberately void by arbitrating an out-of-range index.

## Status & follow-ups

**Done:**
- **Engine:** `CategoricalMarketEngine` with N-outcome parimutuel settlement, the
  hardened posture (two-step admin, zero-address guards, fee snapshot), the
  no-winner / invalid-sentinel voids, and the **opt-in optimistic dispute window**
  (propose → challenge → finalize → admin arbitration, bonded). 22 lifecycle + 10
  dispute tests.
- **Oracle:** the `ICategoricalOracleAdapter` interface + `MockCategoricalOracle`.
- **Properties:** value conservation fuzzed across a two-winner book and across a
  variable outcome count with an arbitrary winner (2 fuzz tests, 512 runs each).

**Next (the rest of the vertical, as it was built out for scalar):**
- a **Chainlink / categorical oracle adapter** for a real winning-index feed;
- **relayer** create-market support (an `outcomeCount` + oracle spec);
- **resolver** settlement driving (`CategoricalWatcher`);
- a **frontend** panel (per-outcome pools, implied probabilities, payout preview);
- **devnet parity** against the real engine, like the binary and scalar engines.
