# OracleForge · Relayer

The bridge between the off-chain AI/Cartesi pipeline and on-chain markets.

```
 AI proposals ──▶ committed Cartesi forecast ──▶ createMarket(Gnosis MarketEngine)
   (generator)        (notice: prob_bps)              (as an authorized relayer)
```

For each AI market proposal the relayer:
1. builds the forecast request and obtains the **committed** result — the `prob_bps`
   from the Cartesi notice (verifiable on-chain), not a local guess;
2. computes the on-chain `questionHash = keccak256(question)` and the predicted
   `marketId`, and abi-encodes the Chainlink `oracleParams`;
3. skips anything already on-chain (idempotent), then submits `createMarket`.

## Why these pieces exist

- **`keccak.py`** — the stdlib's `sha3_256` is *not* Ethereum's keccak256, so the
  relayer can't otherwise compute a `questionHash`/`marketId` that matches the
  Solidity. Pure keccak256, verified against known vectors.
- **`abi.py`** — encodes `oracle_params` as `abi.encode(address,address,int256,uint8,uint64)`
  — byte-identical to what `ChainlinkOracleAdapter.configure` decodes — and
  derives `marketId` from the same packed preimage the engine uses.
- **`notices.py`** — `StubNoticeSource` reproduces the committed forecast in-process
  (same deterministic function the machine runs) for dev/CI/dry-run;
  `GraphQLNoticeReader` reads real notices from a running Cartesi node.
- **`chain.py`** — `GnosisChain` (web3) submits; `DryRunChain` records without a
  network, so the whole pipeline runs locally.
- **`index.py`** — for each freshly-created market, builds a self-describing
  `markets` index row: `market_type` (binary/scalar/categorical) plus a JSON
  `params` blob for the parameters with no dedicated column (the scalar band + unit,
  the categorical outcome labels). A binary market additionally gets a `predictions`
  row (`PredictionIndexRow`): the committed probability, the forecast's reproducible
  95% confidence interval and the Monte Carlo sample count — the AI panel's data.
  Pure escaped SQL through a sink seam (`LogMarketIndexSink` dry-run · a signed
  registry sink is the live swap-in), the creation-time counterpart to the resolver's
  `oracle_reports` write-back. The `markets` catalog is thus populated for all three
  market types, not just binary.

## Run

```bash
# full pipeline with no chain and no live rollup (generator -> stub forecast -> would-submit)
python3 -m oracleforge_relayer.cli --dry-run

# relay sample scalar (range) markets to the ScalarMarketEngine
python3 -m oracleforge_relayer.cli --dry-run --scalar

# relay sample categorical (N-outcome) markets to the CategoricalMarketEngine
python3 -m oracleforge_relayer.cli --dry-run --categorical

# relay a saved proposal set
python3 -m oracleforge_relayer.cli --proposals proposals.json --dry-run

# tests (stdlib only — keccak vectors, ABI layout, mapping, orchestration)
python3 -m unittest discover -s tests -t .
```

## Validation (the write path)

Every proposal is validated before a `createMarket` is built, so a malformed one
is **skipped** (not submitted with bad data, and not surfaced as a batch error):
`close_at` must be in uint64 range and future, `threshold` present and in int256
range, `comparator` ∈ {0,1}, `max_stale` in uint64 range, and the feed must resolve
to an address. Unknown feeds and out-of-range values all skip.

## Scalar & categorical markets

The relayer also creates markets on the other two engines, each a straight
map → create with **no Cartesi forecast** (the market shape, not a probability,
defines it) and the identical marketId derivation, so dedupe is cross-consistent
across all three:

- **scalar** — a `band {lower, upper}` + a scalar oracle spec (`target_decimals`
  instead of threshold/comparator). `build_scalar_create_market_args` /
  `Relayer.run_scalar`; `ScalarGnosisChain` is the live submitter.
  See [`docs/SCALAR-MARKETS.md`](../../docs/SCALAR-MARKETS.md).
- **categorical** — an `outcomes` label list (or `outcome_count`, 2..64) + a
  categorical oracle spec (just the feed(s) + `max_stale`; the winning index is
  what the oracle reports). `build_categorical_create_market_args` /
  `Relayer.run_categorical`; `CategoricalGnosisChain` is the live submitter.
  See [`docs/CATEGORICAL-MARKETS.md`](../../docs/CATEGORICAL-MARKETS.md).

### Submit on-chain

```bash
pip install -e ".[chain,graphql]"      # web3 + requests
export RELAYER_RPC_URL=https://rpc.chiadochain.net
export RELAYER_PK=0x...                 # must be an authorized relayer on the engine
export MARKET_ENGINE_ADDRESS=0x...
export NEXT_PUBLIC_CHAIN=chiado
export RELAYER_NOTICE_SOURCE=graphql    # read real Cartesi notices (default: stub)
export CARTESI_GRAPHQL_URL=http://localhost:8080/graphql
python3 -m oracleforge_relayer.cli --submit
```

The engine gates `createMarket` to relayers (`setRelayer`), so the relayer key
must be authorized first; the CLI checks `isRelayer` and refuses otherwise.

## Feed addresses

`feeds.py` maps symbolic feeds (`EUR/USD`, `ECON/CPI`, `FUNCTIONS/NOAA`) to
resolver addresses. The built-ins are **placeholders** — set real
[Gnosis Chainlink feed](https://docs.chain.link/data-feeds/price-feeds/addresses?network=gnosis)
addresses via the `ORACLEFORGE_FEEDS` env (JSON map) before submitting. Proposals
whose feed has no address are skipped, never submitted with a bogus one.
