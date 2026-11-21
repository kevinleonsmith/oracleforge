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
| `oracle.py` | `StubOracleView`/`ChainOracleView` (binary `resolve()`) · `StubScalarOracleView`/`ChainScalarOracleView` (scalar `latestValue()`) · `StubCategoricalOracleView`/`ChainCategoricalOracleView` (categorical `latestOutcome()`) |
| `chain.py` | `GnosisResolver` (web3) · `DryRunResolver` (no network) — shared `resolve()`/`finalize()` drive all three engines |
| `archive.py` | `LogReportSink` (default) · `TablelandReportSink` → `oracle_reports` INSERT via a `TablelandMutator` (`LogTablelandMutator` dry-run · `RegistryTablelandMutator` signed) |
| `watcher.py` | orchestration: `Watcher` (binary) · `ScalarWatcher` (range) · `CategoricalWatcher` (N-outcome), each `tick()` once / `watch()` loops |

## Scalar & categorical markets

The `ScalarMarketEngine` and `CategoricalMarketEngine` share the same
`resolve()`/`finalize()` lifecycle and dispute window, so `ScalarWatcher` and
`CategoricalWatcher` drive them with the identical propose → wait → finalize flow;
each only differs in what it reads from the oracle and archives:

- **scalar** reads `latestValue()` (a numeric value) and archives the settled value
  (`--dry-run --scalar`). See [`docs/SCALAR-MARKETS.md`](../../docs/SCALAR-MARKETS.md).
- **categorical** reads `latestOutcome()` (the winning index) and archives that
  index, or `-1` for a void when the oracle reports the `0xFF` sentinel
  (`--dry-run --categorical`). See [`docs/CATEGORICAL-MARKETS.md`](../../docs/CATEGORICAL-MARKETS.md).

## Run

```bash
# one tick over a sample spread (no chain): shows wait/pending/resolve/settled
python3 -m oracleforge_resolver.cli --dry-run
python3 -m oracleforge_resolver.cli --dry-run --scalar   # the scalar-market variant
python3 -m oracleforge_resolver.cli --dry-run --categorical # the categorical variant
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
resolution-evidence columns (`market_id`, `market_type`, `feed`, `answer`/settled
value, `outcome`, `reported_at`). The `market_type` (binary/scalar/categorical) makes
each row self-describing: `outcome = 0` is NO for a binary market but *outcome 0 won*
for a categorical one, so without it the index is ambiguous. The archival worker later
back-fills `oracle_reports.arweave_tx` with the Arweave evidence bundle (which carries
`market_type` too).
