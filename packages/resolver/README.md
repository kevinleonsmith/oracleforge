# OracleForge · Resolution Watcher

Settles markets after they close. For each market past its `closeAt` whose oracle
is ready, it pokes the permissionless `MarketEngine.resolve(marketId)` and archives
the outcome as an oracle report.

```
 open markets ──▶ plan (closed? oracle ready?) ──▶ resolve() on Gnosis ──▶ oracle report
   (Tableland/chain)                                   (permissionless)       (Tableland + Arweave)
```

In production this is **Chainlink Automation**; the watcher is the off-chain
driver (and a safety net — anyone can run one, since `resolve()` is open).

## Per-market decision (pure, in `planner.py`)

| Market state | Oracle | Action |
|--------------|--------|--------|
| not past `closeAt` | — (not queried) | **wait** |
| Resolved / Invalid | — (not queried) | **settled**, skip |
| past `closeAt`, open | `Pending` | **pending** (feed not ready) |
| past `closeAt`, open | `Yes` / `No` | **resolve** → poke `resolve()`, archive YES/NO |
| past `closeAt`, open | `Invalid` | **resolve** → market voids, archive as void |

The oracle is only read for markets that are actually closed and unsettled, so a
live watcher makes the minimum number of calls. A double-resolve (two watchers
racing) simply reverts and is logged as a benign error, not a crash.

## Pieces

| File | Role |
|------|------|
| `planner.py` | pure decision function (fully tested) |
| `sources.py` | `StaticMarketSource` (dry-run) · `TablelandMarketSource` (live, read-only) |
| `oracle.py` | `StubOracleView` · `ChainOracleView` (adapter's `resolve()` view) |
| `chain.py` | `GnosisResolver` (web3) · `DryRunResolver` (no network) |
| `archive.py` | `LogReportSink` (default) · `TablelandReportSink` (write TODO) |
| `watcher.py` | orchestration: `tick()` once, `watch()` loops |

## Run

```bash
# one tick over a sample spread (no chain): shows wait/pending/resolve/settled
python3 -m oracleforge_resolver.cli --dry-run

# tests (stdlib only)
python3 -m unittest discover -s tests -t .
```

### Live

```bash
pip install -e ".[chain,tableland]"
export RESOLVER_RPC_URL=https://rpc.chiadochain.net
export RESOLVER_PK=0x...                 # pays gas for resolve(); any funded key
export MARKET_ENGINE_ADDRESS=0x...
export NEXT_PUBLIC_CHAIN=chiado
export MARKETS_TABLE=markets_10200_123   # Tableland physical table name

python3 -m oracleforge_resolver.cli --watch --interval 15   # loop
python3 -m oracleforge_resolver.cli --watch --once          # single tick
```

`resolve()` is permissionless, so the key only needs gas — not relayer authority.
The oracle adapter address is read from `engine.oracle()` unless
`ORACLE_ADAPTER_ADDRESS` overrides it.

## Archival

A settlement produces an `OracleReport` (market, outcome, time, feed, tx). Today
it goes to `LogReportSink`; the `oracle_reports` Tableland row + Arweave evidence
bundle (`oracle_reports.arweave_tx`) land with the archival worker — `archive.py`
already defines the sink interface.
