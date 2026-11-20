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

## Run

```bash
# full pipeline with no chain and no live rollup (generator -> stub forecast -> would-submit)
python3 -m oracleforge_relayer.cli --dry-run

# relay a saved proposal set
python3 -m oracleforge_relayer.cli --proposals proposals.json --dry-run

# tests (stdlib only — keccak vectors, ABI layout, mapping, orchestration)
python3 -m unittest discover -s tests -t .
```

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
