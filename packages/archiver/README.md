# OracleForge · Arweave Archival Worker

Permanent, verifiable storage. Persists immutable artifacts to Arweave and writes
the resulting tx id back onto the relational row in Tableland.

```
 payload ──canonical JSON + sha256──▶ Arweave (permanent) ──▶ Tableland.arweave_tx
            (content hash = integrity)     (tx id)                (relational pointer)
```

Artifacts: market specs + evidence, oracle reports, AI model outputs, governance
proposals, simulations, disputes. Each becomes an immutable Arweave transaction;
the Tableland row keeps the small queryable record and a pointer to the full
payload.

## Content-addressing (the integrity guarantee)

Every payload is serialized canonically (sorted keys, no whitespace) and hashed
with sha256. That hash is:
- stored as the `Content-SHA256` Arweave tag,
- returned in the receipt and written next to the tx id,
- used to **dedupe** — re-archiving identical data returns the existing tx id and
  uploads nothing.

So anyone can fetch the data from Arweave, recompute the hash, and confirm it is
exactly what the protocol recorded. Order-invariant and verified in the tests.

## Pieces

| File | Role |
|------|------|
| `canonical.py` | deterministic JSON + sha256 content hash |
| `tags.py` | Arweave tags (App-Name, Type, Content-SHA256, Table/Row-Id, …) |
| `arweave.py` | `LocalArweaveClient` (content-addressed dir store + manifest) · `TurboArweaveClient` (live, JWK-signed) |
| `tableland.py` | `LogTablelandWriter` · `RegistryTablelandWriter` (signed mutation, TODO) |
| `archiver.py` | orchestration + domain→artifact builders |
| `sinks.py` | `ArweaveReportSink` — plugs into the resolver's `ReportSink` |

## Run

```bash
# archive sample artifacts to a temp content-addressed store (no wallet/network)
python3 -m oracleforge_archiver.cli --dry-run

# archive a JSON array of artifacts to a local store
python3 -m oracleforge_archiver.cli --input bundle.json

# tests (stdlib only)
python3 -m unittest discover -s tests -t .
```

### Live upload

```bash
pip install -e ".[arweave,tableland]"
export ARWEAVE_BACKEND=turbo
export ARWEAVE_WALLET_JSON=/path/to/arweave-key.json   # JWK keyfile
python3 -m oracleforge_archiver.cli --input bundle.json --live
```

## Wiring into the resolver

The resolution watcher archives every settlement by swapping its sink:

```python
from oracleforge_archiver import Archiver
from oracleforge_archiver.arweave import LocalArweaveClient   # or TurboArweaveClient
from oracleforge_archiver.sinks import ArweaveReportSink

archiver = Archiver(LocalArweaveClient("./.arweave-store"))
watcher  = Watcher(resolver, oracle_view, source, ArweaveReportSink(archiver))
```

Each resolved market's oracle report is then permanently archived and its
`oracle_reports.arweave_tx` pointer set — closing the audit trail.
