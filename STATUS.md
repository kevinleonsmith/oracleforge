# OracleForge — Build Status

_Last updated: 2026-11-20_

MVP of an autonomous AI prediction-market protocol on Gnosis Chain. **10 packages,
103 passing tests.** Every off-chain worker, pure-logic layer, smart contract, and
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

## Packages

| Package | Purpose | Lang | Tests | Try it |
|---------|---------|------|-------|--------|
| `contracts` | MarketEngine (parimutuel), Treasury, ForgeToken, Chainlink oracle adapter | Solidity (Foundry) | **3** | `npm run test:contracts` |
| `ai-market-generator` | signals → cluster → confidence → deterministic forecast → proposal | Python | **9** | `npm run ai` |
| `cartesi` | deterministic forecast packaged as a Cartesi Rollups machine (commits notices) | Python + Docker | **9** | `npm run test:cartesi` |
| `relayer` | Cartesi notices → `createMarket` on Gnosis (keccak + ABI encoding) | Python | **15** | `npm run relay` |
| `resolver` | resolution watcher — pokes `resolve()` after close, archives outcomes | Python | **13** | `npm run resolve` |
| `archiver` | Arweave permanent storage + Tableland `arweave_tx` write-back | Python | **12** | `npm run archive` |
| `inference` | Akash GPU service (embeddings + drafting) + SDL; `RemoteEmbedder` | Python + Docker | **18** | `npm run inference` |
| `lit` | token-gated / encrypted private markets (Lit Protocol) | TypeScript | **14** | `npm run lit` |
| `frontend` | Next.js terminal UI; live Tableland + viem reads, switchable with mock | TypeScript | **10** | `npm run dev` |
| `shared` | Tableland SQL schema + shared TypeScript types | SQL + TS | — | — |
| | | | **103** | `npm test` |

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
(stub/remote) forecast equals the generator's local value bit-for-bit.

## Tested vs. live

**Fully built and tested here** (no network, no credentials, no `npm/pip install`):
- All smart contracts (compile + full lifecycle: create → position → Chainlink-fed
  resolve → fee → parimutuel claim → refund).
- Every off-chain worker's logic end to end against stubs/local stores: market
  generation, deterministic forecasting, notice→createMarket mapping (incl. a
  from-scratch keccak256 verified against vectors), resolution planning, content-
  addressed archival with dedupe, inference server+client (generator runs over
  HTTP), and Lit gating with real AES-GCM (holder decrypts, non-holder denied,
  tamper detected).
- Deploy manifests that are generated + validated: the Akash SDL, the Foundry
  deploy script, the Cartesi Dockerfile.

**Coded behind interfaces, NOT exercised** (needs infrastructure/credentials):

| What | Where | Needs |
|------|-------|-------|
| Deployed contracts on Chiado | `contracts/script/Deploy.s.sol` | funded testnet key + RPC |
| Running Cartesi rollup | `cartesi/` (`cartesi build/run`) | Cartesi CLI + Docker + RISC-V |
| On-chain submission | `relayer/chain.py`, `resolver/chain.py` (`GnosisResolver`) | `web3`, RPC, funded key |
| Cartesi GraphQL notices | `relayer/notices.py` (`GraphQLNoticeReader`) | running node |
| Real Arweave upload | `archiver/arweave.py` (`TurboArweaveClient`) | JWK wallet + SDK |
| Signed Tableland writes | `archiver/tableland.py`, resolver sink | web3 + table-owner key |
| GPU model path | `inference/` (`TransformerEmbedder`, `LLMDrafter`) | `torch` + CUDA GPU |
| Akash deployment | `inference/deploy/` | `provider-services` CLI + AKT wallet |
| Lit network encryption | `lit/litClient.ts` (`RealLitClient`) | `@lit-protocol/*` + wallet |
| Frontend live-chain render | `frontend/` (`chainApi.ts`) | a deployment (build itself now runs in CI) |

## CI & branch protection

**CI** (`.github/workflows/ci.yml`) runs on every push to `master`/`main` and on
every PR, as two jobs:

| Check | What it does |
|-------|--------------|
| `all tests` | Node 22 + Python 3.11 + Foundry + PyYAML, runs `npm test` (all 103 tests) |
| `frontend build` | `npm install` + `next build` in `packages/frontend` — compiles the TSX and type-checks the whole app (the one thing the stdlib test suite can't cover) |

Current status (both checks, live):
[![CI](https://github.com/kevinleonsmith/oracleforge/actions/workflows/ci.yml/badge.svg)](https://github.com/kevinleonsmith/oracleforge/actions/workflows/ci.yml)

The repo is **public**, so server-side **rulesets** are active on `master`:

- `protect-master-history` — blocks force-pushes and branch deletion, **no bypass**
  (applies to everyone, owner included).
- `protect-master-ci` — requires both status checks above to pass, with
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
