# OracleForge — Build Status

_Last updated: 2026-11-20_

MVP of an autonomous AI prediction-market protocol on Gnosis Chain. **11 packages,
388 passing tests** (incl. parimutuel settlement fuzzed for its invariants,
stateful solvency proven across randomly-interleaved market histories, and a
cross-package end-to-end that threads one market through every worker). Every
off-chain worker, pure-logic layer, smart contract, and
deploy manifest is built and tested; the live network clients are coded against
standard APIs behind interfaces and remain unexercised without infrastructure and
credentials (see [Tested vs. live](#tested-vs-live)).

> **Not audited. Demonstration MVP — do not use with real funds.**

## At a glance

```
Akash embeddings ─▶ Cartesi deterministic forecast ─▶ relayer createMarket ─▶ trade
       │                                                                          │
       └─ (non-deterministic, suggests only)                                 resolve()
                                                                                  │
   frontend ◀── Tableland index + on-chain reads ◀── Arweave archive ◀───────────┘
                                                      (public + Lit-encrypted)
```

- **Run every test:** `npm test` (contracts via Foundry, the rest via Python `unittest` / `node --test`)
- **Run the pipeline dry (no chain/network):** `npm run ai`, `npm run relay`, `npm run resolve`, `npm run archive`, `npm run lit`, `npm run inference`
- **Run the whole thing end to end:** `npm run e2e` (generate → relay → trade → resolve → archive, with boundary checks)
- **Prove settlement on a real node:** `npm run devnet` (binary) / `npm run devnet:scalar` (scalar) / `npm run devnet:categorical` (categorical) — boots anvil, deploys the actual contracts, checks on-chain payouts == the Python port

## Packages

| Package | Purpose | Lang | Tests | Try it |
|---------|---------|------|-------|--------|
| `contracts` | MarketEngine (parimutuel), Treasury, ForgeToken, Chainlink oracle adapter; **fuzzed settlement + stateful solvency invariants**, **optimistic resolution with a bonded dispute window**, **two-step admin/governor rotation**, **every core contract directly reviewed + tested** (engine, Treasury, token, oracle adapter), **scalar (range) market engine** with proportional parimutuel settlement + **stateful solvency invariants** (clamped either way, mid-band split, one-sided void) + its own dispute window + Chainlink oracle adapter, **categorical (N-outcome) market engine** with winner-take-all parimutuel settlement + fuzzed value conservation + **stateful solvency invariants** (across interleaved N-outcome histories incl. every void path) + its own optimistic dispute window + Chainlink oracle adapter; **all three engines carry stateful solvency invariants** | Solidity (Foundry) | **163** | `npm run test:contracts` |
| `ai-market-generator` | signals → cluster → confidence → deterministic forecast → proposal | Python | **9** | `npm run ai` |
| `cartesi` | deterministic forecast packaged as a Cartesi Rollups machine (commits notices) | Python + Docker | **9** | `npm run test:cartesi` |
| `relayer` | Cartesi notices → `createMarket` on Gnosis (keccak + ABI encoding); **validated write path**, **creates binary, scalar and categorical markets** | Python | **46** | `npm run relay` |
| `resolver` | resolution watcher — proposes `resolve()`, waits out the dispute window, `finalize()`s, archives outcomes; **drives binary, scalar and categorical engines** (`Watcher` / `ScalarWatcher` / `CategoricalWatcher`); **`oracle_reports` write-back** (built, escaped SQL through a signed-mutation seam) | Python | **67** | `npm run resolve` |
| `archiver` | Arweave permanent storage + Tableland `arweave_tx` write-back | Python | **12** | `npm run archive` |
| `inference` | Akash GPU service (embeddings + drafting) + SDL; `RemoteEmbedder` | Python + Docker | **18** | `npm run inference` |
| `lit` | token-gated / encrypted private markets (Lit Protocol) | TypeScript | **14** | `npm run lit` |
| `frontend` | Next.js terminal UI; live Tableland + viem reads, switchable with mock; **optimistic-resolution panel** (live challenge countdown, dispute/finalize); **scalar-market panel** (band, implied value, live LONG/SHORT payout); **categorical-market panel** (per-outcome implied probabilities, winner-take-all payout preview) | TypeScript | **32** | `npm run dev` |
| `shared` | Tableland SQL schema + shared TypeScript types | SQL + TS | — | — |
| `integration` | end-to-end thread across every worker + contract-exact settlement (binary + scalar + categorical ports); **anvil devnet** parity vs the real `MarketEngine`, `ScalarMarketEngine` **and `CategoricalMarketEngine`** | Python + Foundry | **18** (+8 devnet) | `npm run e2e` · `npm run devnet*` |
| | | | **388** | `npm test` |

## The determinism boundary (the key design decision)

Two compute paths, split on purpose:

- **Deterministic (Cartesi):** anything committed on-chain — the initialized
  probability, resolution math. Fixed-seed PRNG, reproducible byte-for-byte across
  nodes and on fraud-proof replay. `ai-market-generator/oracleforge_ai/cartesi.py`
  + `cartesi/`.
- **Non-deterministic (Akash GPU):** heavy embeddings / LLM drafting that only
  *suggest* markets. Never produces committed state, so commodity GPUs are safe.
  `inference/`, behind the `Embedder` protocol.

A proof of this runs in CI: the relayer and inference tests assert the committed
(stub/remote) forecast equals the generator's local value bit-for-bit — and the
`integration` suite re-proves it across the full relay path, end to end.

## Tested vs. live

**Fully built and tested here** (no network, no credentials, no `npm/pip install`):
- All smart contracts (compile + full lifecycle: create → position → Chainlink-fed
  resolve → fee → parimutuel claim → refund), with the settlement **fuzzed for its
  invariants** (value conservation, exact fee, no overpay, claim guards, invalid
  refunds — 512 runs each) and **stateful invariants** that drive randomly-
  interleaved create/position/resolve/claim sequences across many markets and
  actors, asserting the engine stays solvent (balance + payouts + fees == deposits)
  and the treasury holds exactly the fees skimmed, after any history. The
  **scalar and categorical engines carry the same stateful solvency suite** — the
  scalar one spans oracle values below / inside / above the band (clamped either
  way, a mid-band split) plus the one-sided-book void; the categorical one uses
  random outcome counts and a resolve step that reaches every settlement path — a
  funded winner and all three voids (no-winner, out-of-range, invalid sentinel) —
  so the continuous scalar payout and the dynamic N-outcome pools array are both
  proven solvent across arbitrary histories too. An internal
  **security review** ([`docs/SECURITY-REVIEW.md`](docs/SECURITY-REVIEW.md)) found
  and fixed a fund-locking bug (a no-winner market stranded the losing pool),
  pinned the protocol fee to each market at creation so it can't be changed
  mid-flight, added a two-step (`Ownable2Step`-style) admin rotation so a lost key
  isn't terminal, and guarded the constructor against zero addresses — every
  actionable finding (F1–F6) is now fixed in-tree with a regression test. A
  **second pass** audited the `Treasury` and `ForgeToken` directly (previously
  only exercised through MarketEngine): it added the same two-step governor
  rotation and zero-address guard, and a `sweep` that reconciles tokens sent to
  the treasury outside `collectFee` (otherwise unrecoverable), backed by a
  `totalReserved` running total with the invariant
  `sum(buckets) == totalReserved <= balance`; both contracts now have dedicated
  suites (T1–T4). A **third pass** audited the `ChainlinkOracleAdapter` (O1–O4):
  it now rejects non-positive feed answers (a negative glitch could have settled a
  market the wrong way) and enforces that a fallback feed shares the primary's
  decimals, with the staleness/scaling/outcome semantics documented and tested.
  Every core contract — engine, Treasury, token, oracle adapter — now has a direct
  review and its own suite.
- **Optimistic resolution with a dispute window** (opt-in): with a nonzero
  `challengeWindow`, `resolve()` only *proposes* an outcome; it must survive the
  window — or an admin arbitration of a bonded `dispute()` — before `finalize()`
  opens claims. A rejected challenge forfeits its bond to the treasury, an upheld
  one is refunded and the admin's ruling becomes authoritative. The default
  window of 0 keeps the original instant-settlement path, so the feature is
  strictly additive. The **resolver worker** drives this end to end — it proposes
  `resolve()`, waits out the challenge window, then `finalize()`s and archives the
  outcome only once it's final (reading the engine's `challengeWindow`), while a
  zero window keeps its original one-shot resolve-and-archive behavior. The
  **frontend** closes the loop: an optimistic-resolution panel derives each
  market's phase (proposed → challenge countdown → disputed/frozen → finalizable)
  from the same raw chain fields (`readDisputeState`), with the phase logic pure
  and unit-tested. The feature now spans all three layers — contract, worker, UI.
- **Scalar (range) markets** ([`docs/SCALAR-MARKETS.md`](docs/SCALAR-MARKETS.md)):
  a second engine (`ScalarMarketEngine`) for numeric questions — traders take
  LONG/SHORT on a `[lower, upper]` band and the pot is split by where the oracle's
  value lands (`f = (clamp(v) - lower) / (upper - lower)`), so both sides can be
  paid, unlike binary winner-take-all. Built with the same hardened posture (two-
  step admin, zero-address guards, fee snapshotted at creation, one-sided-book
  void) and proven with **fuzzed value conservation** and **LONG-payout
  monotonicity** (512 runs each). Settles from a real feed via
  `ScalarChainlinkAdapter`, which reports a Chainlink answer rescaled to the band's
  unit (reusing the O1/O3 health logic, and handling mismatched-decimals fallbacks
  without the binary adapter's O2 constraint); an end-to-end test settles an engine
  market through it. Also carries its own **opt-in optimistic dispute window**
  (propose → challenge → finalize → admin arbitration, bonded; a zero window keeps
  atomic settlement), so an admin can override a bad feed value with the authoritative
  one. The **resolver** operates it end to end: `ScalarWatcher` reuses the shared
  `resolve()`/`finalize()` lifecycle to drive propose → wait → finalize, reading the
  scalar oracle's `latestValue()` and archiving the settled value
  (`--dry-run --scalar`). The **frontend** renders a Scalar Markets panel — the band,
  the pools' implied settlement value, and a live LONG/SHORT payout preview as you
  drag a hypothetical settlement point (payout math in `lib/scalar.ts`, unit-tested).
  Scalar markets are now at parity with binary across contract → oracle → worker →
  UI. Binary `MarketEngine` is untouched and independent.
- **Categorical (N-outcome) markets** ([`docs/CATEGORICAL-MARKETS.md`](docs/CATEGORICAL-MARKETS.md)):
  a third engine (`CategoricalMarketEngine`) for "which one?" questions — `N`
  mutually-exclusive outcomes (`2..64`), traders stake on one, and the winning pool
  takes the whole losing pot (net of fee) pro-rata. It is the binary engine
  generalized from 2 outcomes to N (a test pins the `N = 2` == binary equivalence),
  built with the same hardened posture (two-step admin, zero-address guards, fee
  snapshot) and the no-winner / invalid-sentinel voids (the oracle reports an
  out-of-range index to cancel). Proven with **fuzzed value conservation** across a
  two-winner book and a variable outcome count with an arbitrary winner (512 runs
  each), via `ICategoricalOracleAdapter` + `MockCategoricalOracle`. It also carries
  its own **opt-in optimistic dispute window** (propose → challenge → finalize → admin
  arbitration, bonded); unlike the scalar engine's structural one-sided void, the
  categorical voids (out-of-range/invalid index, or a winning pool with no stake)
  depend on the final outcome, so they are decided at finalization — a dispute can move
  the winner to a funded outcome, or an admin can void by ruling an out-of-range index.
  The **resolver** operates it: `CategoricalWatcher` reuses the shared
  `resolve()`/`finalize()` lifecycle to drive propose → wait → finalize, reading the
  categorical oracle's `latestOutcome()` (a winning index) and archiving it, or `-1`
  for a void (`--dry-run --categorical`). The **relayer** creates them:
  `Relayer.run_categorical` maps an `outcomes` list (or `outcome_count`, 2..64) + a
  categorical oracle spec to `CategoricalMarketEngine.createMarket`, with the same
  marketId derivation (cross-consistent dedupe) and `CategoricalGnosisChain` as the
  live submitter — so categorical markets are created and settled by the workers end
  to end. Settlement can read a real feed via `CategoricalChainlinkAdapter`, which
  reports the winning index a Functions consumer posts (sharing the health posture,
  but treating `0` as a valid index and an overflowing answer as the void sentinel);
  an end-to-end test settles a real engine market through it. The **frontend** renders
  a Categorical Markets panel — each outcome's book-implied probability as a bar, and a
  winner-take-all payout preview (including the sole-funded-outcome void) for the picked
  outcome (math in `lib/categorical.ts`, unit-tested). So categorical markets now reach
  full parity with binary and scalar across contract → oracle → worker → UI. Binary and
  scalar engines are untouched and independent.
- Every off-chain worker's logic end to end against stubs/local stores: market
  generation, deterministic forecasting, notice→createMarket mapping (incl. a
  from-scratch keccak256 verified against vectors), resolution planning, content-
  addressed archival with dedupe, inference server+client (generator runs over
  HTTP), and Lit gating with real AES-GCM (holder decrypts, non-holder denied,
  tamper detected).
- Deploy manifests that are generated + validated: the Akash SDL, the Foundry
  deploy script, the Cartesi Dockerfile.
- A **cross-package end-to-end** (`integration/`) that threads one market through
  all four Python workers and asserts the boundary holds: a single `market_id`
  from relay through resolve to archive, the committed forecast equal to the
  generator's, parimutuel settlement value-conserving against a contract-exact
  port of `MarketEngine.claim`, and stable content-addressed dedupe.
- An **anvil devnet** (`integration/anvil/`) that removes that port from the trust
  path: it boots a real node, deploys the **actual** Solidity, runs the full
  on-chain lifecycle (create → position → resolve → claim) via `cast`, and asserts
  the real `MarketEngine` payouts and fee equal the Python `settle()` to the wei —
  and the same for the **`ScalarMarketEngine`** (`scalar_devnet.py`, checked against
  `scalar_settle()` across mid-band, clamped, and one-sided-void scenarios) and the
  **`CategoricalMarketEngine`** (`categorical_devnet.py`, checked against
  `categorical_settle()` across a funded winner, an empty-outcome void, and the
  invalid sentinel).

**Coded behind interfaces, NOT exercised** (needs infrastructure/credentials):

| What | Where | Needs |
|------|-------|-------|
| Deployed contracts on Chiado | `contracts/script/Deploy.s.sol` | funded testnet key + RPC |
| Running Cartesi rollup | `cartesi/` (`cartesi build/run`) | Cartesi CLI + Docker + RISC-V |
| On-chain submission | `relayer/chain.py`, `resolver/chain.py` (`GnosisResolver`) | `web3`, RPC, funded key |
| Cartesi GraphQL notices | `relayer/notices.py` (`GraphQLNoticeReader`) | running node |
| Real Arweave upload | `archiver/arweave.py` (`TurboArweaveClient`) | JWK wallet + SDK |
| Signed Tableland mutation | `archiver` `RegistryTablelandWriter`, resolver `RegistryTablelandMutator` (the INSERT/UPDATE SQL is built + tested; only the signed tx is unexercised) | web3 + table-owner key |
| GPU model path | `inference/` (`TransformerEmbedder`, `LLMDrafter`) | `torch` + CUDA GPU |
| Akash deployment | `inference/deploy/` | `provider-services` CLI + AKT wallet |
| Lit network encryption | `lit/litClient.ts` (`RealLitClient`) | `@lit-protocol/*` + wallet |
| Frontend live-chain render | `frontend/` (`chainApi.ts`) | a deployment (build itself now runs in CI) |

## CI & branch protection

**CI** (`.github/workflows/ci.yml`) runs on every push to `master`/`main` and on
every PR, as three jobs:

| Check | What it does |
|-------|--------------|
| `all tests` | Node 22 + Python 3.11 + Foundry + PyYAML, runs `npm test` (all 388 tests) |
| `frontend build` | `npm install` + `next build` in `packages/frontend` — compiles the TSX and type-checks the whole app (the one thing the stdlib test suite can't cover) |
| `anvil devnet parity` | boots a real anvil node, deploys the actual contracts, and asserts on-chain payouts equal the Python ports — binary `MarketEngine` vs `settle()`, `ScalarMarketEngine` vs `scalar_settle()`, and `CategoricalMarketEngine` vs `categorical_settle()` (`npm run test:devnet`) |

Current status (all checks, live):
[![CI](https://github.com/kevinleonsmith/oracleforge/actions/workflows/ci.yml/badge.svg)](https://github.com/kevinleonsmith/oracleforge/actions/workflows/ci.yml)

A frozen snapshot of this badge (captured at **CI – passing**) is checked in at
`docs/ci-badge.svg`: ![CI snapshot](docs/ci-badge.svg) — the live badge above is the source of truth.

The repo is **public**, so server-side **rulesets** are active on `master`:

- `protect-master-history` — blocks force-pushes and branch deletion, **no bypass**
  (applies to everyone, owner included).
- `protect-master-ci` — requires all three status checks above to pass, with
  `strict` up-to-date-before-merge; owner retains admin bypass for direct pushes.

A **local** `pre-push` guard (`scripts/install-git-hooks.sh`) additionally blocks
force-pushes / deletion of `master` client-side; install it in each clone with
`bash scripts/install-git-hooks.sh`.

## Toolchains verified in this environment

Node 22.14 · Python 3.11 · Foundry 1.5.1 · git. (No Docker, no `npm install`, no
GPU, no chain RPC — hence the boundary above.)

## Path to a running deployment

1. `forge script Deploy --broadcast` to Chiado → `frontend` `npm run extract-addresses`.
2. `cartesi build && cartesi run`; point the relayer at its GraphQL (`RELAYER_NOTICE_SOURCE=graphql`).
3. `pip install -e ".[chain]"` for relayer + resolver; fund a key; run them.
4. `make build push` the inference image; `provider-services` deploy the Akash SDL.
5. Wire `TurboArweaveClient` + a signed Tableland writer for real archival.
6. `cd frontend && npm install && NEXT_PUBLIC_DATA_SOURCE=chain npm run dev`.

See each package's `README.md` for specifics, and `ARCHITECTURE.md` for the module map.
