# OracleForge

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
│  ├─ shared/               Tableland SQL schema + shared TypeScript types
│  └─ frontend/             Next.js 14 terminal UI (viem + wagmi + Tableland SDK)
├─ infra/                   deployment topology notes (Cartesi / Akash / Arweave / Lit)
└─ .github/workflows/       CI (forge test + python unittest)
```

See **[ARCHITECTURE.md](./ARCHITECTURE.md)** for the module map and data flow.

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
`ChainlinkOracleAdapter.configure` decodes. The frontend reads markets through
`lib/api.ts` (mock today, Tableland + viem when live) using the shared types.

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
| Tableland schema + shared types | ✅ defined |
| Frontend | ✅ scaffold on mock data (needs `npm install`) |
| Akash / Arweave / Lit integrations | ⬜ interfaces + env wired, clients TODO |
| LMSR/AMM pricing, dispute module, staking | ⬜ roadmap |
