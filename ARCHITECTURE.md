# OracleForge — Architecture

## Design priorities
Deterministic AI execution · verifiable computation · composability · decentralization · modularity.

## Component map

| Layer | Tech | Responsibility | In this repo |
|-------|------|----------------|--------------|
| Market generation | Python, (LangChain/HF on Akash) | ingest signals → cluster → propose markets → forecast | `packages/ai-market-generator` |
| Deterministic compute | Cartesi Machine | reproducible Monte Carlo / Bayesian forecasts, fraud-proofable | `packages/cartesi` (machine image + rollup dApp); core in `oracleforge_ai/cartesi.py` |
| Settlement | Solidity / Gnosis Chain | market lifecycle, parimutuel payout, fees, treasury | `packages/contracts` |
| Oracle | Chainlink Data Feeds / Functions / Automation | resolve markets from real-world data | `src/oracle/ChainlinkOracleAdapter.sol` |
| Relational index | Tableland | queryable markets, predictions, positions, proposals | `packages/shared/tableland` |
| Permanent storage | Arweave | immutable question text, model output, evidence, disputes | `*_arweave_tx` columns |
| Private markets | Lit Protocol | token-gated / encrypted markets and alpha | `packages/lit` (ACC builders + gated encryption; archives via the Arweave worker) |
| GPU compute | Akash | scalable inference/training for the non-deterministic path | `packages/inference` (stdlib server + SDL); `RemoteEmbedder` plugs into the generator |
| Interface | Next.js + viem + wagmi | terminal UI, wallet, dashboards | `packages/frontend` |

## Determinism boundary (the important one)

Two compute paths, split on purpose:

- **Deterministic path (Cartesi):** anything whose result is committed on-chain —
  the initialized probability, resolution-relevant math. Fixed-seed PRNG, integer
  math where it matters, output byte-identical across nodes so a fraud proof can
  replay it. Packaged as a Cartesi Rollups dApp in `packages/cartesi`: the
  forecast runs inside the RISC-V machine and is emitted as a **notice**. Core in
  `cartesi.py` + `HashingEmbedder` (no model download inside the machine).
- **Non-deterministic path (Akash GPU):** heavy embeddings / LLM drafting that
  only *suggests* markets. Its output is an input to the deterministic path, never
  a settlement authority. Swapped in behind `TransformerEmbedder` / the LLM
  question-drafting interface.

## Market lifecycle

1. **Generate** — `MarketGenerator.propose()` clusters signals, dedupes against
   open markets, scores confidence, and sets `ai_prob_bps` via the Cartesi
   forecaster. Emits a `MarketProposal`.
2. **Create** — an authorized relayer calls `MarketEngine.createMarket(...)` with
   the proposal's fields; the engine calls `oracle.configure(...)` with the
   abi-encoded feed/threshold/comparator.
3. **Trade** — users `takePosition(marketId, side, amount)` into YES/NO pools.
4. **Resolve** — after `closeAt`, `resolve(marketId)` (Chainlink Automation in
   prod) reads the adapter; a protocol fee is skimmed from the losing pool to the
   Treasury.
5. **Claim** — winners `claim(marketId)` for principal + pro-rata share of the
   fee-reduced losing pool. Invalid markets refund both sides.

## Security notes (MVP posture)
- Parimutuel (not AMM) to keep settlement math auditable in the scaffold.
- Oracle redundancy: primary + fallback feed, staleness guard, `Pending` (never
  auto-`Invalid`) when no healthy feed — avoids griefing resolution.
- Relayer-gated market creation; fee capped at 10%; governor-gated treasury.
- **Not audited.** Threat model (oracle manipulation, flash-loan, sybil,
  governance capture, AI hallucination containment) is roadmap, per the protocol
  spec prompt.
