# OracleForge · Frontend

Next.js 14 terminal UI. Reads markets from **either** a mock data set (design time)
or **live** from the deployed Chiado contracts + Tableland index — switched by one
env var, with no page changes.

```
NEXT_PUBLIC_DATA_SOURCE=mock    # design-time sample data (default)
NEXT_PUBLIC_DATA_SOURCE=chain   # Tableland index + live on-chain pools/status
```

## Data flow (chain mode)

```
 Tableland gateway ──SQL──▶ markets/predictions/proposals rows ──▶ map to domain types
                                                                      │
 MarketEngine.getMarket(id) ──live pools/status──▶ hydrate each market┘ ──▶ page
```

`lib/api.ts` is a thin facade over `mockApi.ts` and `chainApi.ts`. The live client
queries Tableland over HTTP (read-only, no SDK) for the indexed rows, then refreshes
each market's mutable fields (`yesPool`/`noPool`/`status`/`outcome`) from the chain
via viem. Any failure (gateway down, not deployed, RPC hiccup) degrades to the
indexed row or an empty state — it never crashes the page.

| File | Role |
|------|------|
| `lib/api.ts` | facade: picks mock or chain by `NEXT_PUBLIC_DATA_SOURCE`; serves binary, scalar + categorical markets |
| `lib/queries.ts` | **pure** SQL builders + row→domain mappers + stats (unit-tested) |
| `lib/format.ts` | **pure** bps/units/compact formatting (unit-tested) |
| `lib/tableland.ts` | read-only gateway query |
| `lib/contracts.ts` | viem client + ABIs + `readMarketOnchain` / `readScalarMarketOnchain` / `readCategoricalMarketOnchain` (all three engines) |
| `lib/marketDecode.ts` | **pure** scalar/categorical `getMarket` tuple decoders (unit-tested) |
| `lib/marketHydrate.ts` | **pure** merge of live pools into the scalar/categorical card defs (unit-tested) |
| `lib/addresses.ts` | deployment address book (`deployments/*.json` + env override) |
| `scripts/extract-addresses.mjs` | write the address book from a Foundry broadcast |

## Interactive terminal (client components)

`app/page.tsx` fetches markets/proposals server-side and hands them to `Terminal`,
a client shell with tab + hash routing (`#markets` / `#simulations` / `#governance`):

| Component | What it does |
|-----------|--------------|
| `Terminal` | tabs + `#hash` routing across the three views |
| `MarketsView` | clickable market cards → trade drawer; live "Your Positions" tracker |
| `TradeDrawer` | pick YES/NO + stake, live parimutuel **payout preview** (`payoutPreview`), place a demo position |
| `SimulationExplorer` | sliders (bias/horizon/volatility) re-run a **deterministic** Monte Carlo fan with a stable input hash |
| `GovernanceView` | proposals with live demo voting + treasury allocation |
| `ProbabilityChart` | shared SVG line chart (engine + simulation) |

Trading and voting are **local demo state** — nothing is sent on-chain. The payout
math (`lib/format.ts → payoutPreview`) is the same parimutuel settlement
`MarketEngine.claim` uses, and is unit-tested (`npm test`).

## Connect to a deployment

```bash
# 1) deploy the contracts (packages/contracts) — one run brings up all three
#    engines (binary, scalar, categorical) + their oracle adapters
cd ../contracts
forge script script/Deploy.s.sol:Deploy --rpc-url chiado --broadcast --private-key $DEPLOYER_PK

# 2) extract addresses into the frontend's address book (captures all three engines)
cd ../frontend
npm run extract-addresses -- \
  ../contracts/broadcast/Deploy.s.sol/10200/run-latest.json \
  deployments/chiado.json --network chiado

# 3) point the app at the chain and run
export NEXT_PUBLIC_DATA_SOURCE=chain
export NEXT_PUBLIC_CHAIN=chiado
export NEXT_PUBLIC_RPC_URL=https://rpc.chiadochain.net
export NEXT_PUBLIC_TABLELAND_GATEWAY=https://tableland.network
export NEXT_PUBLIC_MARKETS_TABLE=markets_10200_123   # physical table name
npm install && npm run dev
```

Addresses can also be set directly with `NEXT_PUBLIC_MARKET_ENGINE` /
`NEXT_PUBLIC_ORACLE_ADAPTER` without editing the JSON.

## Tests

The pure data logic (SQL building, row mapping, stats, formatting, broadcast
extraction) is unit-tested and runs with Node alone — no install, no browser:

```bash
npm test
```

The full app build/render (`npm run build`) needs `npm install` and is not run here.
