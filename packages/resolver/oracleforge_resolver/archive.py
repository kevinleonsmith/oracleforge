"""Report sinks — where settlement records go for audit.

When the watcher settles a market it emits an ``OracleReport``; a ``ReportSink``
persists it. Two sinks ship:

- ``LogReportSink`` — collects reports in memory and logs them (default; dev/CI).
- ``TablelandReportSink`` — turns each report into an ``oracle_reports`` INSERT
  and sends it through a ``TablelandMutator``. The statement is built purely
  (``OracleReportRow.sql``) and is identical whether it is logged in a dry-run
  (``LogTablelandMutator``) or signed and broadcast on-chain
  (``RegistryTablelandMutator``, the live path). The row the archiver later
  back-fills with ``arweave_tx`` is the one written here.

A Tableland write is an on-chain mutation against the TablelandTables registry,
so the *only* seam that needs a signer + RPC is ``RegistryTablelandMutator``;
everything up to the signed tx — mapping, column order, SQL, escaping — is pure
and tested here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Protocol

from .models import OracleReport

logger = logging.getLogger("oracleforge.resolver.archive")

DEFAULT_REPORTS_TABLE = "oracle_reports"


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


# --------------------------------------------------------------------------- #
# oracle_reports row — the SQL is pure, so it is identical in dry-run and live  #
# --------------------------------------------------------------------------- #
def _q(value: str) -> str:
    """Quote a SQL string literal, escaping embedded single quotes."""
    return "'" + str(value).replace("'", "''") + "'"


@dataclass
class OracleReportRow:
    """One ``oracle_reports`` row built from an ``OracleReport``.

    The resolver supplies the *resolution-evidence* columns it actually
    observes — ``market_id``, ``market_type`` (binary/scalar/categorical, so the
    row is self-describing), ``feed``, ``answer`` (the raw oracle answer, or the
    settled value for a scalar market), ``outcome`` and ``reported_at``. The
    ``market_type`` matters because ``outcome`` is ambiguous without it: ``0`` is
    NO for a binary market, the (unused) scalar default, and the *winning index*
    for a categorical one — a consumer can only tell which from ``market_type``.
    The ``comparator``/``threshold`` columns are *creation-time* market parameters
    the resolver does not carry at settlement, so they default (``0`` / ``''``);
    the row that owns them is written at ``createMarket`` time by the indexer.
    ``arweave_tx`` is left unset — the archiver back-fills it once the evidence
    bundle is stored (``UPDATE ... SET arweave_tx``). ``id`` is omitted so
    Tableland/SQLite auto-assigns the primary key.
    """

    market_id: str
    feed: str
    answer: str
    outcome: int
    reported_at: int
    market_type: str = "binary"
    comparator: int = 0
    threshold: str = ""
    round_id: Optional[str] = None

    @classmethod
    def from_report(cls, r: OracleReport) -> "OracleReportRow":
        return cls(
            market_id=r.market_id,
            feed=r.feed,
            answer="" if r.answer is None else str(r.answer),
            outcome=r.outcome,
            reported_at=r.resolved_at,
            market_type=r.kind,
            round_id=(r.tx_hash or None),
        )

    def sql(self, table: str = DEFAULT_REPORTS_TABLE) -> str:
        cols = ["market_id", "market_type", "feed", "answer", "comparator",
                "threshold", "outcome", "reported_at"]
        vals = [_q(self.market_id), _q(self.market_type), _q(self.feed),
                _q(self.answer), str(self.comparator), _q(self.threshold),
                str(self.outcome), str(self.reported_at)]
        if self.round_id is not None:
            cols.append("round_id")
            vals.append(_q(self.round_id))
        return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(vals)});"


# --------------------------------------------------------------------------- #
# Mutator seam — the signed on-chain write is the ONLY unexercised part         #
# --------------------------------------------------------------------------- #
class TablelandMutator(Protocol):
    def mutate(self, statement: str) -> None: ...


class LogTablelandMutator:
    """Records the statements it would send (dev/CI/dry-run)."""

    def __init__(self):
        self.statements: List[str] = []

    def mutate(self, statement: str) -> None:
        self.statements.append(statement)
        logger.info("tableland <- %s", statement)


class RegistryTablelandMutator:
    """Signed mutation via the TablelandTables registry (web3). Live path."""

    def __init__(self, rpc_url: str, registry_address: str, table_id: int,
                 chain_id: int, private_key: str):
        self.rpc_url = rpc_url
        self.registry_address = registry_address
        self.table_id = table_id
        self.chain_id = chain_id
        self.private_key = private_key

    def mutate(self, statement: str) -> None:  # pragma: no cover - needs chain + signer
        raise NotImplementedError(
            "RegistryTablelandMutator.mutate: sign & send a mutate() tx to the "
            f"TablelandTables registry for statement: {statement}"
        )


class TablelandReportSink:
    """Persists each settlement as an ``oracle_reports`` INSERT.

    Builds the statement from the report and hands it to a ``TablelandMutator``.
    The default ``LogTablelandMutator`` makes the sink fully usable (and testable)
    without a chain; pass a ``RegistryTablelandMutator`` for the live signed write.
    Collected ``rows`` are kept for inspection/idempotency checks.
    """

    def __init__(self, table: str = DEFAULT_REPORTS_TABLE,
                 mutator: Optional[TablelandMutator] = None):
        self.table = table
        self.mutator = mutator or LogTablelandMutator()
        self.rows: List[OracleReportRow] = []

    def record(self, report: OracleReport) -> None:
        row = OracleReportRow.from_report(report)
        self.rows.append(row)
        self.mutator.mutate(row.sql(self.table))
