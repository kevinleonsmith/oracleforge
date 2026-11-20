"""Adapters that connect the archiver to other OracleForge services.

``ArweaveReportSink`` satisfies the resolver's ``ReportSink`` protocol (duck-typed:
a ``.record(report)`` method), so the resolution watcher can archive every
settlement to Arweave with a one-line swap:

    from oracleforge_archiver.sinks import ArweaveReportSink
    watcher = Watcher(resolver, oracle_view, source, ArweaveReportSink(archiver))
"""
from __future__ import annotations

from typing import Any, List

from .archiver import Archiver, artifact_from_oracle_report
from .models import Receipt


class ArweaveReportSink:
    def __init__(self, archiver: Archiver):
        self.archiver = archiver
        self.receipts: List[Receipt] = []

    def record(self, report: Any) -> None:
        self.receipts.append(self.archiver.archive(artifact_from_oracle_report(report)))
