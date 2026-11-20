"""Archival orchestration + domain → artifact builders.

    payload ──canonical+hash──▶ Arweave (permanent) ──▶ Tableland arweave_tx write-back

Dedupe is by content hash: re-archiving identical data returns the existing tx id
and does not re-upload. Each builder turns a domain object (market, oracle report,
prediction, proposal, simulation) into an ``Artifact`` pointed at the right
Tableland row.
"""
from __future__ import annotations

import logging
import time
from typing import Any, List, Optional

from .arweave import ArweaveClient
from .canonical import canonical_bytes, content_hash
from .models import Artifact, ArtifactKind, Receipt
from .tableland import TablelandWriter, WriteBack
from .tags import build_tags

logger = logging.getLogger("oracleforge.archiver")


class Archiver:
    def __init__(self, client: ArweaveClient, writer: Optional[TablelandWriter] = None, now_fn=None):
        self.client = client
        self.writer = writer
        self._now = now_fn or (lambda: int(time.time()))

    def archive(self, artifact: Artifact) -> Receipt:
        data = canonical_bytes(artifact.payload)
        ch = content_hash(artifact.payload)
        tags = build_tags(artifact, ch, now=self._now())

        tx_id, deduped = self.client.put(data, tags, content_hash=ch)
        url = self.client.url(tx_id)

        written = False
        if self.writer is not None:
            self.writer.set_arweave_tx(
                WriteBack(artifact.table, artifact.id_column, artifact.row_id,
                          artifact.tx_column, tx_id)
            )
            written = True

        return Receipt(
            content_hash=ch, tx_id=tx_id, url=url, size=len(data),
            kind=artifact.kind.value, deduped=deduped, written_back=written, tags=tags,
        )

    def archive_many(self, artifacts: List[Artifact]) -> List[Receipt]:
        receipts = [self.archive(a) for a in artifacts]
        n_new = sum(1 for r in receipts if not r.deduped)
        logger.info("archived %d artifact(s): %d new, %d deduped",
                    len(receipts), n_new, len(receipts) - n_new)
        return receipts


# ------------------------------------------------------------- domain builders

def _field(obj: Any, name: str, default=None):
    """Read from a dataclass/object or a dict."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def artifact_from_market(market: dict) -> Artifact:
    mid = market["market_id"] if "market_id" in market else market["question_hash"]
    return Artifact(
        kind=ArtifactKind.MARKET,
        payload=market,
        table="markets", id_column="market_id", row_id=str(mid),
        extra_tags={"Market-Id": str(mid), "Category": str(market.get("category", ""))},
    )


def artifact_from_oracle_report(report: Any) -> Artifact:
    mid = str(_field(report, "market_id"))
    payload = {
        "market_id": mid,
        "outcome": _field(report, "outcome"),
        "resolved_at": _field(report, "resolved_at"),
        "feed": _field(report, "feed", ""),
        "settlement_tx": _field(report, "tx_hash", ""),
        "answer": _field(report, "answer"),
    }
    return Artifact(
        kind=ArtifactKind.ORACLE_REPORT,
        payload=payload,
        table="oracle_reports", id_column="market_id", row_id=mid,
        extra_tags={"Market-Id": mid, "Outcome": str(payload["outcome"])},
    )


def artifact_from_prediction(prediction: dict) -> Artifact:
    mid = str(prediction["market_id"])
    return Artifact(
        kind=ArtifactKind.PREDICTION,
        payload=prediction,
        table="predictions", id_column="market_id", row_id=mid,
        extra_tags={"Market-Id": mid, "Model": str(prediction.get("model", ""))},
    )


def artifact_from_governance(proposal: dict) -> Artifact:
    pid = str(proposal["proposal_id"])
    return Artifact(
        kind=ArtifactKind.GOVERNANCE,
        payload=proposal,
        table="governance_proposals", id_column="proposal_id", row_id=pid,
        extra_tags={"Proposal-Id": pid},
    )


def artifact_from_simulation(sim: dict) -> Artifact:
    sid = str(sim.get("id", sim.get("market_id", "")))
    return Artifact(
        kind=ArtifactKind.SIMULATION,
        payload=sim,
        table="simulations", id_column="id", row_id=sid,
        extra_tags={"Kind": str(sim.get("kind", ""))},
    )
