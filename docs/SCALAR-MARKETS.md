# OracleForge — Scalar (Range) Markets

Binary markets answer a yes/no question. **Scalar markets** answer a *numeric* one
— "where will ETH close?", "what will CPI print?" — by paying out along a continuum
instead of winner-take-all. `ScalarMarketEngine` is the contract foundation;
`MarketEngine` (binary) is unchanged and independent.

> MVP scaffold, not audited. Built with the same hardened posture as the binary
> engine (two-step admin, zero-address guards, fee snapshotted at creation,
> one-sided-book void).

## The model

A market defines a band `[lower, upper]`. Traders take a side:

- **LONG** — profits as the settlement value rises toward `upper`.
- **SHORT** — profits as it falls toward `lower`.

At settlement the oracle reports a value `v`, which the engine **clamps** into the
band and converts to a fraction:

```
cv = clamp(v, lower, upper)
f  = (cv - lower) / (upper - lower)        ∈ [0, 1]
```

The whole pot (both pools) is settled, minus the protocol fee:

```
pot           = longPool + shortPool
fee           = pot * feeBps / 10_000      (snapshotted at creation; default 2%)
distributable = pot - fee
longPayout    = distributable * f          (LONG side's collective share)
shortPayout   = distributable - longPayout (SHORT takes the remainder — no dust)
```

Each trader then takes their **pro-rata share of their own side's** payout:

```
myPayout = longPayout  * myLongStake  / longPool
         + shortPayout * myShortStake / shortPool
```

So unlike the binary engine, both sides can be paid: LONG gets more the higher `v`
settles, SHORT more the lower. A trader can lose part of their stake (their side's
share is small) or more than double it (their side's share is large and they hold a
big fraction of it).

## Worked example

Band `[100, 200]`, LONG pool 600, SHORT pool 400 (pot 1000), fee 2% → distributable
980.

| Settlement `v` | `f` | LONG side | SHORT side |
|---|---|---|---|
| 50 → clamps to 100 | 0.0 | 0 | 980 |
| 150 | 0.5 | 490 | 490 |
| 999 → clamps to 200 | 1.0 | 980 | 0 |

At `v = 150`, a trader holding the entire 600 LONG pool receives `490 * 600/600 =
490` — they staked 600 and got 490 back (a loss), while the sole SHORT trader staked
400 and received 490 (a gain). Value is conserved: `490 + 490 + 20 (fee) = 1000`.

## Edge cases & guarantees

- **One-sided book** → the market **voids** (status `Invalid`) and every principal
  is refunded, no fee taken. With no counterparty there's nothing to settle, and
  paying a clamped fraction would strand the empty side's share — the same push
  handling as the binary engine's no-winner case (review finding F1).
- **Clamping** means a value outside the band is not an error: below `lower` pays
  SHORT everything, above `upper` pays LONG everything.
- **Value conservation** holds for any book and any settlement value:
  `sum(payouts) + fee + dust == deposits`, where `dust` is sub-wei floor-division
  rounding retained in the contract (bounded by the number of claimants). Proven by
  `testFuzz_settlementConservesValue` (512 runs).
- **Monotonicity:** a higher settlement value never pays the LONG side less —
  `testFuzz_longPayoutMonotoneInValue` (512 runs).
- **Fee is snapshotted** at creation, so an admin can't change the economics of an
  in-flight market (review finding F2).

## Oracle

Scalar settlement needs a raw number, not a yes/no, so it uses a separate
`IScalarOracleAdapter` (`latestValue(marketId) -> (ready, value)`) rather than the
binary `IOracleAdapter`. `MockScalarOracle` drives the tests; a production adapter
would wrap a Chainlink feed's answer directly (with the same staleness/decimals
care as `ChainlinkOracleAdapter`, review O1–O4).

## Status & follow-ups

**Done (this stage):** the engine, the scalar oracle interface + mock, and the full
test suite (14 lifecycle/settlement + 2 fuzz properties).

**Not yet wired:**
- A production `ScalarChainlinkAdapter` (read a feed's value, clamp/validate).
- An **optimistic dispute window** — v1 settles atomically; the binary engine's
  propose → challenge → finalize flow is the pattern to port.
- **Resolver** support (the watcher drives only binary `resolve` today).
- **Frontend** rendering (a range slider / implied-value readout instead of
  YES/NO odds).
