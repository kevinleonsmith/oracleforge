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

`CategoricalChainlinkAdapter` is the production adapter: it reads a feed (e.g. a
Chainlink Functions consumer that posts a match/election/award result as an
integer) and reports that winning index. It shares the binary/scalar adapters'
health posture with one categorical twist — `0` is a **valid** outcome index, so
only a *negative* answer is rejected (never `== 0`), alongside a zero timestamp and
staleness (`maxStale == 0` disables it). An answer that overflows `uint8` is out of
any valid range, so it is reported as the invalid sentinel `0xFF` and the engine
voids (the engine makes the final range check against the market's own
`outcomeCount`). No decimal rescaling — an index is a plain integer. An end-to-end
test settles a real `CategoricalMarketEngine` market from a mock feed through it.

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
- **Oracle:** the `ICategoricalOracleAdapter` interface + `MockCategoricalOracle`,
  and the production `CategoricalChainlinkAdapter` (15 tests, incl. an end-to-end
  settle through the engine).
- **Properties:** value conservation fuzzed across a two-winner book and across a
  variable outcome count with an arbitrary winner (2 fuzz tests, 512 runs each).
- **Relayer:** `build_categorical_create_market_args` / `Relayer.run_categorical`
  create categorical markets on the `CategoricalMarketEngine` — an `outcomes` label
  list (or `outcome_count`, validated 2..64) plus a categorical oracle spec (just the
  feed(s) + `max_stale`; the winning index is what the oracle reports, so no
  threshold/band). No Cartesi forecast is threaded, and the marketId derivation is
  identical, so dedupe is cross-consistent with binary and scalar.
  `CategoricalGnosisChain` is the live submitter (`--dry-run --categorical`).
- **Resolver:** `CategoricalWatcher` drives the shared `resolve()`/`finalize()`
  lifecycle from the categorical oracle's `latestOutcome()`, archiving the winning
  index (or `-1` for a void). It reuses the same propose → wait → finalize flow and
  the dispute window, differing only in reading a winning index instead of a yes/no
  or a number (`--dry-run --categorical`). The out-of-range sentinel `0xFF` is the
  void signal. 10 planner + 7 watcher tests.

- **Devnet parity:** `integration/anvil/categorical_devnet.py` boots a real anvil
  node, deploys the actual `CategoricalMarketEngine` + `MockCategoricalOracle`, runs
  the full N-outcome lifecycle on-chain, and asserts the payouts equal a Python port
  (`pipeline.categorical_settle`) **to the wei** — across a funded winner (pro-rata
  split, losers' claims revert), an empty winning outcome (void), and the oracle's
  invalid sentinel (void). So categorical settlement is checked against the contract
  it mirrors, in CI (`npm run test:devnet`), exactly as the binary and scalar engines are.

- **Frontend:** a Categorical Markets panel (`components/CategoricalMarketCard.tsx`)
  renders each outcome as a row — its book-implied probability (the pool's share of the
  pot) as a bar you can click to price — and previews the winner-take-all payout for a
  demo stake on the picked outcome, including the sole-funded-outcome **void** (push,
  stake refunded). The math lives in `lib/categorical.ts` (`impliedProbabilities`,
  `categoricalPayoutPreview`, `favorite`), a pure mirror of the contract's claim,
  unit-tested with `node --test` (6 tests, incl. the docs worked example reproduced to
  the unit). So categorical markets now reach **full parity with binary and scalar**
  across contract → oracle → worker → UI.

So categorical markets are now **created and settled by the workers** end to end, on
top of the contract engine and its dispute window, with the settlement math proven
on-chain and surfaced in the UI — the full vertical, as it was built out for scalar.
