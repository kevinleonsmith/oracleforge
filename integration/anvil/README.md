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

```bash
npm run devnet        # run it as a demo (prints on-chain vs port, side by side)
npm run test:devnet   # run it as assertions (YES and NO outcomes)
```

```
  ACCOUNT     ON-CHAIN       PORT
  0xAlice         1070       1070  ✓
  0xBob            713        713  ✓
  fee               16         16  ✓
  PARITY: on-chain == Python port
```

## How it stays honest

- **Real contracts, real node.** `MarketEngine`, `Treasury`, `MockERC20` and a
  settable `MockOracleAdapter` are deployed with `forge create` to a live anvil;
  positions, resolution and claims are real transactions read back from event
  logs. The only shortcut is the oracle outcome (set directly, so the harness
  controls YES/NO — the Chainlink-fed path is covered by the Foundry tests).
- **One scenario, two engines.** The positions come from `pipeline.DEMO_POSITIONS`,
  so the devnet and the pure pipeline settle the identical trades; the test
  asserts the Solidity result matches `settle(...)`.
- **Ephemeral + self-cleaning.** Each run picks a random port and tears the node
  down in a `finally`, so repeated or parallel runs never collide.

## Requirements

The Foundry toolchain (`anvil`, `forge`, `cast`) on `PATH`. `test:devnet` **skips
cleanly** when they are absent, so it never breaks a toolchain-less run — the pure
`integration/` suite always runs regardless. In CI it is its own job
(`anvil devnet parity`).
