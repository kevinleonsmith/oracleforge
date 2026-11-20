"""Archiver CLI.

    python -m oracleforge_archiver.cli --dry-run           # archive samples to a local store
    python -m oracleforge_archiver.cli --input bundle.json  # archive a JSON array of artifacts
    python -m oracleforge_archiver.cli --input b.json --live # upload to Arweave (needs wallet)

Each input item: {"kind": "...", "payload": {...}, "table": "...",
"id_column": "...", "row_id": "...", "extra_tags": {...}}.
"""
from __future__ import annotations

import argparse
import json
import logging
import tempfile


def _sample_artifacts():
    from .archiver import (artifact_from_governance, artifact_from_market,
                           artifact_from_oracle_report)

    market = {
        "market_id": "0xa7f3", "question": "Will US CPI print below 2.6% YoY for December 2026?",
        "category": "MACRO", "close_at": 1740800000,
        "evidence": ["Fed officials signal a possible 50bps cut", "CPI 2.6% YoY, below consensus"],
    }
    report = {"market_id": "0xa7f3", "outcome": 1, "resolved_at": 1740900000,
              "feed": "ECON/CPI", "tx_hash": "0xabc", "answer": 255}
    proposal = {"proposal_id": "OFP-47", "title": "Allocate 1.2M $FORGE to Akash GPU reserve",
                "body": "Rationale...", "for_votes": "72", "against_votes": "19"}
    return [
        artifact_from_market(market),
        artifact_from_oracle_report(report),
        artifact_from_governance(proposal),
    ]


def _load_artifacts(path: str):
    from .models import Artifact, ArtifactKind

    with open(path) as f:
        items = json.load(f)
    return [
        Artifact(
            kind=ArtifactKind(it["kind"]), payload=it["payload"], table=it["table"],
            id_column=it["id_column"], row_id=str(it["row_id"]),
            tx_column=it.get("tx_column", "arweave_tx"), extra_tags=it.get("extra_tags", {}),
        )
        for it in items
    ]


def _print(receipts) -> None:
    print(f"{'KIND':<14} {'NEW?':<7} {'SIZE':>5}  TX / URL")
    print("-" * 82)
    for r in receipts:
        tag = "dedup" if r.deduped else "new"
        wb = " · tableland✓" if r.written_back else ""
        print(f"{r.kind:<14} {tag:<7} {r.size:>5}  {r.url}")
        print(f"{'':<14} └─ sha256 {r.content_hash}{wb}")


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="oracleforge-archiver")
    ap.add_argument("--dry-run", action="store_true", help="archive sample artifacts to a temp local store")
    ap.add_argument("--input", help="path to a JSON array of artifacts")
    ap.add_argument("--live", action="store_true", help="upload to Arweave (needs ARWEAVE_WALLET_JSON)")
    ap.add_argument("--store", help="local store dir (default: temp in dry-run, config otherwise)")
    args = ap.parse_args(argv)

    from .archiver import Archiver
    from .config import Config
    from .tableland import LogTablelandWriter

    cfg = Config.from_env()
    artifacts = _load_artifacts(args.input) if args.input else _sample_artifacts()

    if args.live and args.input:
        from .arweave import TurboArweaveClient

        client = TurboArweaveClient(cfg.gateway, cfg.wallet_path)
    else:
        from .arweave import LocalArweaveClient

        store = args.store or (tempfile.mkdtemp(prefix="arweave-") if args.dry_run else cfg.local_store)
        client = LocalArweaveClient(store)

    writer = LogTablelandWriter()
    archiver = Archiver(client, writer)
    receipts = archiver.archive_many(artifacts)

    # demonstrate idempotency in the dry-run: re-archiving dedupes
    if args.dry_run:
        again = archiver.archive(artifacts[0])
        assert again.deduped, "expected dedupe on re-archive"

    _print(receipts)
    new = sum(1 for r in receipts if not r.deduped)
    print(f"\n{new} new, {len(receipts) - new} deduped; {len(writer.writes)} Tableland write-back(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
