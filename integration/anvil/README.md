# OracleForge · Anvil devnet (settlement parity)

The pure end-to-end (`../pipeline.py`) settles trades with a Python **port** of
`MarketEngine.claim`. This variant takes the port out of the trust path: it boots
a real **anvil** node, deploys the **actual Solidity contracts**, and runs the
whole lifecycle on-chain —

```
deploy → createMarket → takePosition ×N → advance time → resolve → claim ×N
```

— driving every step with `cast`, then asserts the **on-chain payouts and fee
equal the Python `settle()` port to the wei**, for the same scenario
(`pipeline.DEMO_POSITIONS`). If the port ever drifts from the contract, this fails.

The same treatment covers the **scalar** engine (`scalar_devnet.py`): it deploys
the real `ScalarMarketEngine` + `MockScalarOracle`, runs the LONG/SHORT lifecycle,
and asserts the on-chain payouts equal the `scalar_settle()` port across three
scenarios — a value inside the band (both sides paid), a clamped value (LONG takes
all, SHORT claims 0 without reverting), and a one-sided **void** (principals
refunded).

And the **categorical** engine (`categorical_devnet.py`): it deploys the real
`CategoricalMarketEngine` + `MockCategoricalOracle`, runs the N-outcome lifecycle,
and asserts the on-chain payouts equal the `categorical_settle()` port across a
funded winner (winning pool splits the pot pro-rata, losers' claims revert), an
empty winning outcome (**void**, refunded), and the oracle's invalid sentinel
(**void**, refunded).

```bash
npm run devnet              # binary demo (prints on-chain vs port, side by side)
npm run devnet:scalar       # scalar demo (mid-band / clamp / void scenarios)
npm run devnet:categorical  # categorical demo (winner / empty-void / invalid-void)
npm run test:devnet         # all parity assertions (binary ×2 + scalar ×3 + categorical ×3)
```

```
  ACCOUNT     ON-CHAIN       PORT
  0xAlice         1070       1070  ✓
  0xBob            713        713  ✓
  fee               16         16  ✓
  PARITY: on-chain == Python port
```

## How it stays honest

- **Real contracts, real node.** For binary, `MarketEngine`, `Treasury`,
  `MockERC20` and a settable `MockOracleAdapter`; for scalar, `ScalarMarketEngine`
  and `MockScalarOracle`; for categorical, `CategoricalMarketEngine` and
  `MockCategoricalOracle` — all deployed with `forge create` to a live anvil.
  Positions, resolution and claims are real transactions read back from event
  logs. The only shortcut is the oracle value (set directly, so the harness
  controls the outcome — the Chainlink-fed paths are covered by the Foundry tests).
- **One book per engine, checked to the wei.** The binary positions come from
  `pipeline.DEMO_POSITIONS`, the scalar from `SCALAR_DEMO_POSITIONS`, the
  categorical from `CATEGORICAL_DEMO_POSITIONS`, so the devnet and the port settle
  the identical books; each test asserts the Solidity result matches its Python
  port (`settle` / `scalar_settle` / `categorical_settle`) to the wei.
- **Ephemeral + self-cleaning.** Each run picks a random port and tears the node
  down in a `finally`, so repeated or parallel runs never collide.

## Requirements

The Foundry toolchain (`anvil`, `forge`, `cast`) on `PATH`. `test:devnet` **skips
cleanly** when they are absent, so it never breaks a toolchain-less run — the pure
`integration/` suite always runs regardless. In CI it is its own job
(`anvil devnet parity`).
