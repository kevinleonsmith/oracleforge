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
| past `closeAt`, open | `Yes` / `No` | **resolve** → propose `resolve()`, archive YES/NO* |
| past `closeAt`, open | `Invalid` | **resolve** → market voids, archive as void* |
| proposed (`Closed`), window open | — | **wait** (challenge window) |
| proposed (`Closed`), window elapsed | re-read for the label | **finalize** → `finalize()`, archive |

\* When the engine's `challengeWindow` is 0 (the default) `resolve()` settles
atomically, so the watcher archives in that same step — the original behavior.
With a nonzero window, `resolve()` only *proposes*: the watcher reports `proposed`
and holds off archiving until a later tick drives `finalize()` once the window
passes (and no dispute is open). The window is read from `engine.challengeWindow()`.

The oracle is only read for markets that are actually closed and unsettled, so a
live watcher makes the minimum number of calls. A double-resolve or an early
finalize (two watchers racing, or a live dispute) simply reverts and is logged as
a benign error, not a crash.

## Pieces

| File | Role |
|------|------|
| `planner.py` | pure decision function — `plan` (binary) · `plan_scalar` (range) |
| `sources.py` | `StaticMarketSource` (dry-run) · `TablelandMarketSource` (live, read-only) |
| `oracle.py` | `StubOracleView`/`ChainOracleView` (binary `resolve()`) · `StubScalarOracleView`/`ChainScalarOracleView` (scalar `latestValue()`) |
| `chain.py` | `GnosisResolver` (web3) · `DryRunResolver` (no network) — shared `resolve()`/`finalize()` drive both engines |
| `archive.py` | `LogReportSink` (default) · `TablelandReportSink` → `oracle_reports` INSERT via a `TablelandMutator` (`LogTablelandMutator` dry-run · `RegistryTablelandMutator` signed) |
| `watcher.py` | orchestration: `Watcher` (binary) · `ScalarWatcher` (range), each `tick()` once / `watch()` loops |

## Scalar (range) markets

The `ScalarMarketEngine` shares the same `resolve()`/`finalize()` lifecycle, so
`ScalarWatcher` drives it with the identical propose → wait → finalize flow; it
only differs in reading the scalar oracle's `latestValue()` (a numeric value, not a
yes/no) and archiving the settled value. See [`docs/SCALAR-MARKETS.md`](../../docs/SCALAR-MARKETS.md).

## Run

```bash
# one tick over a sample spread (no chain): shows wait/pending/resolve/settled
python3 -m oracleforge_resolver.cli --dry-run
python3 -m oracleforge_resolver.cli --dry-run --scalar   # the scalar-market variant
python3 -m oracleforge_resolver.cli --dry-run --tableland # also print the oracle_reports INSERTs

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

A settlement produces an `OracleReport` (market, outcome, time, feed, tx). The
default `LogReportSink` keeps it in memory; `TablelandReportSink` turns it into an
`oracle_reports` **INSERT** and sends it through a `TablelandMutator`. The statement
is built purely (`OracleReportRow.sql`, escaped and column-ordered to the shared
schema) and is identical whether a dry-run logs it (`LogTablelandMutator`, what
`--tableland` uses) or the live path signs and broadcasts it
(`RegistryTablelandMutator`). So the whole write-back — mapping, column order, SQL,
escaping — is exercised and tested; the only unexercised seam is the signed
registry mutation (needs a writer key + RPC). The resolver fills the
resolution-evidence columns (`market_id`, `feed`, `answer`/settled value, `outcome`,
`reported_at`); the archival worker later back-fills `oracle_reports.arweave_tx`
with the Arweave evidence bundle.
