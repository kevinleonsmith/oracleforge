# OracleForge · Integration (end-to-end)

The per-package suites test each worker in isolation. This package tests that the
workers **agree with each other** — it threads a single market through every
stage using the real module APIs, no network and no install:

```
generate ─▶ relay ─▶ trade / settle ─▶ resolve ─▶ archive
(ai)        (relayer)  (contract math)   (resolver)  (archiver)
```

```bash
npm run e2e          # run the pipeline as a demo (prints each stage + checks)
npm run test:e2e     # run it as assertions (part of `npm test`)
```

## What it proves across the package boundary

| Check | Guarantee |
|-------|-----------|
| **identity** | the `market_id` is derived once (by the relayer, `keccak256`-based) and is **unchanged** when the resolver settles it and the archiver stores it — generator → relayer → resolver → archiver all key the same market. |
| **determinism** | the forecast committed on the relay path equals the generator's local probability **bit-for-bit** — the Cartesi determinism boundary, proven end to end rather than per-unit. |
| **settlement** | `settle()` is a byte-for-byte port of `MarketEngine.claim` (integer math, 2% fee skimmed from the losing pool). Value is conserved: `winners + fee + dust == total staked`, with `dust` the same floor-division remainder Solidity leaves in the contract. |
| **archival** | content-addressing is stable — re-archiving the identical market artifact **dedupes to the same `sha256`**. |

## How it stays honest

`pipeline.py` imports the **actual** package modules (`oracleforge_ai`,
`oracleforge_relayer`, `oracleforge_resolver`, `oracleforge_archiver`) — it does
not re-implement them. It drives the dry-run chain (`DryRunChain`), the stub
committed notice, the stub oracle view, and a local Arweave store, so it exercises
the same code paths the live workers use, minus the network clients. If any
package changes a shape the next stage depends on, a test here goes red.
