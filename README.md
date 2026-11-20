# OracleForge

[![CI](https://github.com/kevinleonsmith/oracleforge/actions/workflows/ci.yml/badge.svg)](https://github.com/kevinleonsmith/oracleforge/actions/workflows/ci.yml)

**Autonomous AI prediction-market protocol.** AI agents generate markets from
real-world signals, heavy forecasting runs as *deterministic* off-chain compute,
markets settle through decentralized oracles, and every artifact is permanently
auditable. Built for Gnosis Chain with Cartesi, Chainlink, Arweave, Lit Protocol,
Akash and Tableland.

> **MVP scaffold.** Contracts compile and are tested; the AI pipeline runs on the
> Python stdlib; the frontend is a wired Next.js app on mock data. The
> decentralized-infra integrations (Cartesi rollup, Akash, Arweave, Lit) are
> defined behind interfaces and stubbed deterministically so the whole thing runs
> locally. **Not audited — do not use with real funds.**

## Monorepo layout

```
oracleforge/
├─ packages/
│  ├─ contracts/            Foundry — MarketEngine, Treasury, ForgeToken, Chainlink adapter
│  ├─ ai-market-generator/  Python — signals → cluster → confidence → forecast → proposal
│  ├─ cartesi/              Cartesi Rollups dApp — deterministic forecast in a RISC-V machine
│  ├─ relayer/              Cartesi notices → createMarket on Gnosis (keccak + ABI, dry-run)
│  ├─ resolver/             resolution watcher — pokes resolve() after close, archives outcomes
│  ├─ archiver/             Arweave archival worker — permanent storage + Tableland write-back
│  ├─ inference/            Akash GPU inference service (embeddings + drafting) + SDL
│  ├─ lit/                  Lit Protocol — token-gated/encrypted private markets
│  ├─ shared/               Tableland SQL schema + shared TypeScript types
│  └─ frontend/             Next.js 14 terminal UI (viem + wagmi + Tableland SDK)
├─ infra/                   deployment topology notes (Cartesi / Akash / Arweave / Lit)
└─ .github/workflows/       CI (forge test + python unittest)
```

See **[STATUS.md](./STATUS.md)** for the per-package build status (tested vs. live)
and **[ARCHITECTURE.md](./ARCHITECTURE.md)** for the module map and data flow.

## Quick start

Prereqs: **Node ≥ 20**, **Python ≥ 3.10**, **[Foundry](https://getfoundry.sh)**.

```bash
cp .env.example .env            # fill in RPC + testnet key for deploys

# 1) Smart contracts — build & test (no external libs; builds offline)
cd packages/contracts && forge test -vv

# 2) AI market generator — run the pipeline (stdlib only, no pip install)
cd ../ai-market-generator
python3 -m oracleforge_ai.cli --format table        # human-readable
python3 -m oracleforge_ai.cli --emit-calldata       # createMarket args as JSON
python3 -m unittest discover -s tests -t .           # tests

# 3) Frontend
cd ../frontend && npm install && npm run dev         # http://localhost:3000
```

From the repo root, `npm test` runs both the contract and AI test suites.

## How the pieces connect

```
  signals ──▶ AI generator (Python / Cartesi) ──▶ MarketProposal
                                                      │ createMarket(questionHash, closeAt, aiProbBps, oracleParams)
                                                      ▼
  trader ──takePosition──▶ MarketEngine (Gnosis) ──configure──▶ ChainlinkOracleAdapter
                                   │ resolve()  ◀──reads feed──────────┘
                                   ├── fee ──▶ Treasury
                                   └── claim ──▶ winners (parimutuel)

  all artifacts (question text, model output, oracle evidence, disputes)
        ──▶ Arweave (permanent)  +  Tableland (queryable relational index)
```

`packages/ai-market-generator` emits proposals whose fields map 1:1 onto
`MarketEngine.createMarket`, and whose `oracleParams` abi-encode exactly what
`ChainlinkOracleAdapter.configure` decodes. **`packages/relayer`** closes the loop:
it takes each proposal, obtains the committed forecast from the Cartesi notice,
and submits `createMarket` on Gnosis as an authorized relayer (`npm run relay`
runs this end-to-end with no chain). After markets close, **`packages/resolver`**
pokes the permissionless `resolve()` once each oracle is ready. **`packages/archiver`**
then persists the full artifacts (question text, oracle evidence, model outputs,
governance) to Arweave and writes the tx id back into the Tableland `*_arweave_tx`
columns — content-addressed so the permanent record is verifiable (`npm run archive`
runs a dry-run; it also plugs into the resolver as a `ReportSink`). The **frontend**
reads markets through `lib/api.ts`, which switches between mock data and live reads
(Tableland index + on-chain pool/status hydration via viem) on one env var —
`NEXT_PUBLIC_DATA_SOURCE=chain` points it at the deployed Chiado contracts (see
`packages/frontend/README.md`).

## Deploy (Chiado testnet)

```bash
cd packages/contracts
forge script script/Deploy.s.sol:Deploy \
  --rpc-url chiado --broadcast --private-key $DEPLOYER_PK
```

## Status & next steps

| Area | State |
|------|-------|
| Market engine + treasury + Chainlink adapter | ✅ compiles, 3 passing lifecycle tests |
| AI generator pipeline | ✅ runs on stdlib, 9 passing tests |
| Cartesi rollup packaging | ✅ machine image + rollup dApp, 9 passing handler tests (see `packages/cartesi`) |
| Relayer (notices → createMarket) | ✅ keccak256 + ABI encoding + orchestration, 15 passing tests, runnable dry-run |
| Resolution watcher (poke resolve + archive) | ✅ planner + orchestration, 13 passing tests, runnable dry-run |
| Arweave archival worker | ✅ content-addressed store + Tableland write-back, 12 passing tests, runnable dry-run |
| Tableland schema + shared types | ✅ defined |
| Frontend | ✅ live data wiring (Tableland + viem) switchable with mock; 10 passing pure-logic tests |
| Akash GPU inference service + SDL | ✅ stdlib server + urllib client + Akash SDL, 18 passing tests (runs generator over HTTP) |
| Lit private markets (token-gated encryption) | ✅ ACC builders + gated AES mock + real-SDK path, 14 passing tests, runnable demo |
| Live clients (Lit SDK, Arweave upload, signed Tableland, GPU model, Akash deploy) | ⬜ all defined behind interfaces; unexercised without network/wallets |
| LMSR/AMM pricing, dispute module, staking | ⬜ roadmap |
