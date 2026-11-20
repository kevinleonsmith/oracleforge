# Deployment topology

```
                         ┌──────────────────────────┐
   signals ─────────────▶│  AI generator (Akash GPU)│  non-deterministic drafting
                         │  HF embeddings + LLM     │
                         └────────────┬─────────────┘
                                      │ proposal priors
                         ┌────────────▼─────────────┐
                         │  Cartesi Machine (rollup)│  deterministic forecast + fraud proofs
                         └────────────┬─────────────┘
                                      │ createMarket (relayer)
  ┌─────────────┐        ┌────────────▼─────────────┐        ┌──────────────┐
  │  Chainlink  │◀──────▶│  MarketEngine (Gnosis)   │───────▶│   Treasury   │
  │ feeds/autom.│ resolve│  Treasury · ForgeToken   │  fees  │  (Gnosis DAO)│
  └─────────────┘        └────────────┬─────────────┘        └──────────────┘
                                      │ index / archive
                   ┌──────────────────┴──────────────────┐
                   ▼                                      ▼
            ┌────────────┐                         ┌────────────┐
            │ Tableland  │  queryable relational   │  Arweave   │  permanent audit trail
            └──────┬─────┘                         └────────────┘
                   │ gateway reads
            ┌──────▼─────┐
            │  Frontend  │  Next.js on Vercel / IPFS
            └────────────┘
```

## What runs where

| Service | Host | Notes |
|---------|------|-------|
| MarketEngine / Treasury / ForgeToken / OracleAdapter | Gnosis Chain (Chiado for testnet) | `forge script Deploy` |
| Deterministic forecasting | Cartesi rollup (Docker machine image) | reproducible; fraud-proofed |
| AI inference / embeddings | Akash deployment (SDL) | autoscaled GPU workers |
| Relational index | Tableland (Gnosis) | schema in `packages/shared/tableland` |
| Permanent storage | Arweave | pointers stored in Tableland rows |
| Private markets | Lit Protocol (`datil` network) | token-gated decryption |
| Frontend | Vercel or IPFS | reads gateway + RPC |
| Automation | Chainlink Automation | pokes `resolve()` at `closeAt` |

TODO: Cartesi machine `Dockerfile` + rollup config, Akash `deploy.yaml` (SDL),
Arweave archival worker, Lit encryption flow. Interfaces for all four already
exist in the codebase; these directories hold their deployment manifests.
