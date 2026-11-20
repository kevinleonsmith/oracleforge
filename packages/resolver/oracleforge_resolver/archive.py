"""Report sinks — where settlement records go for audit.

In production a settlement writes an ``oracle_reports`` row to Tableland and the
full evidence bundle to Arweave (filling ``oracle_reports.arweave_tx``). Those
clients are the next integration; here the sink is an in-memory/log collector so
the watcher is complete and testable end to end.
"""
from __future__ import annotations

import json
import logging
from typing import List, Protocol

from .models import OracleReport

logger = logging.getLogger("oracleforge.resolver.archive")


class ReportSink(Protocol):
    def record(self, report: OracleReport) -> None: ...


class LogReportSink:
    """Collects reports in memory and logs them (default sink)."""

    def __init__(self):
        self.reports: List[OracleReport] = []

    def record(self, report: OracleReport) -> None:
        self.reports.append(report)
        logger.info(
            "archived report %s -> outcome=%s", report.market_id, report.outcome
        )


class TablelandReportSink:
    """Writes oracle_reports rows via a mutate endpoint (signing TODO).

    Left as an interface: Tableland writes are on-chain mutations that must be
    signed by the table owner/writer. Wire this to the Tableland SDK (or a relayer
    tx) when the archival worker lands.
    """

    def __init__(self, gateway_url: str, table: str):
        self.gateway_url = gateway_url
        self.table = table

    def record(self, report: OracleReport) -> None:  # pragma: no cover - needs signer
        raise NotImplementedError(
            "Tableland writes require a signed mutation; "
            f"would INSERT into {self.table}: {json.dumps(report.__dict__)}"
        )
