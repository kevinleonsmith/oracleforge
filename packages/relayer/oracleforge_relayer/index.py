"""Markets-index row builder — serialize a created market into a ``markets`` row.

The resolver writes settlement evidence to ``oracle_reports``; this is the
creation-time counterpart for the ``markets`` catalog the frontend reads. It is
pure SQL (no chain, no network), so it is fully unit-tested, and it mirrors the
resolver's ``OracleReportRow``: escaped, column-ordered to the shared schema, and
identical whether a dry-run logs it or a signed path sends it.

A market is **self-describing** via ``market_type`` (binary/scalar/categorical)
plus a JSON ``params`` blob carrying the type-specific creation parameters that
have no dedicated column — the scalar ``[lower, upper]`` band (and display unit)
and the categorical outcome labels. Binary markets carry ``params = "{}"`` (their
``ai_prob_bps`` is a first-class column). Live pools/status are not written here:
they are mutable and read from the engine, so the row is the immutable catalog.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, List, Optional, Protocol

logger = logging.getLogger("oracleforge.relayer.index")

DEFAULT_MARKETS_TABLE = "markets"


def _q(value: Any) -> str:
    """Single-quote and escape a value for safe inlining into a SQL literal."""
    return "'" + str(value).replace("'", "''") + "'"


@dataclass
class MarketIndexRow:
    """One ``markets`` row built from a create-market args object.

    The resolver-side ``oracle_reports`` row records *settlement* evidence; this
    records the *creation* parameters. ``market_type`` + ``params`` keep the row
    self-describing without a per-type column explosion.
    """

    market_id: str
    question: str
    question_hash: str
    category: str
    market_type: str
    params: str          # JSON; "{}" for a binary market
    ai_prob_bps: int     # 0 for scalar/categorical (not a committed-probability market)
    created_at: int
    close_at: int

    @classmethod
    def from_binary(cls, args, category: str = "", created_at: int = 0) -> "MarketIndexRow":
        return cls(
            market_id=args.market_id, question=args.question,
            question_hash=args.question_hash, category=category,
            market_type="binary", params="{}",
            ai_prob_bps=int(args.ai_prob_bps),
            created_at=int(created_at), close_at=int(args.close_at),
        )

    @classmethod
    def from_scalar(cls, args, category: str = "", unit: str = "",
                    created_at: int = 0) -> "MarketIndexRow":
        params = json.dumps(
            {"feed": args.feed, "lower": int(args.lower), "upper": int(args.upper),
             "unit": unit},
            sort_keys=True,
        )
        return cls(
            market_id=args.market_id, question=args.question,
            question_hash=args.question_hash, category=category,
            market_type="scalar", params=params, ai_prob_bps=0,
            created_at=int(created_at), close_at=int(args.close_at),
        )

    @classmethod
    def from_categorical(cls, args, category: str = "",
                         outcomes: Optional[List[str]] = None,
                         created_at: int = 0) -> "MarketIndexRow":
        body: dict = {"feed": args.feed, "outcome_count": int(args.outcome_count)}
        if outcomes:
            body["outcomes"] = list(outcomes)
        params = json.dumps(body, sort_keys=True)
        return cls(
            market_id=args.market_id, question=args.question,
            question_hash=args.question_hash, category=category,
            market_type="categorical", params=params, ai_prob_bps=0,
            created_at=int(created_at), close_at=int(args.close_at),
        )

    def sql(self, table: str = DEFAULT_MARKETS_TABLE) -> str:
        cols = ["market_id", "question", "question_hash", "category", "market_type",
                "params", "ai_prob_bps", "created_at", "close_at"]
        vals = [_q(self.market_id), _q(self.question), _q(self.question_hash),
                _q(self.category), _q(self.market_type), _q(self.params),
                str(self.ai_prob_bps), str(self.created_at), str(self.close_at)]
        return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(vals)});"


DEFAULT_PREDICTIONS_TABLE = "predictions"
DEFAULT_MODEL = "forge-forecast-mc"


@dataclass
class PredictionIndexRow:
    """One ``predictions`` row built from a committed Cartesi forecast notice. Binary
    markets carry an AI forecast (probability + a deterministic 95% confidence
    interval + the Monte Carlo sample count), which the frontend's AI panel reads;
    this is the index write for it, the prediction-side counterpart to the market
    INSERT. Scalar/categorical markets carry no forecast, so they have no row."""

    market_id: str
    model: str
    prob_yes_bps: int
    ci_low_bps: int
    ci_high_bps: int
    samples: int
    input_hash: str
    computed_at: int

    @classmethod
    def from_notice(cls, market_id: str, notice: dict, computed_at: int,
                    model: str = DEFAULT_MODEL) -> "PredictionIndexRow":
        prob = int(notice["prob_bps"])
        return cls(
            market_id=market_id, model=model, prob_yes_bps=prob,
            # the CI defaults to a point (prob) if an older notice lacks the bounds
            ci_low_bps=int(notice.get("ci_low_bps", prob)),
            ci_high_bps=int(notice.get("ci_high_bps", prob)),
            samples=int(notice.get("samples", 0)),
            input_hash=str(notice.get("input_hash", "")),
            computed_at=int(computed_at),
        )

    def sql(self, table: str = DEFAULT_PREDICTIONS_TABLE) -> str:
        cols = ["market_id", "model", "prob_yes_bps", "ci_low_bps", "ci_high_bps",
                "samples", "input_hash", "computed_at"]
        vals = [_q(self.market_id), _q(self.model), str(self.prob_yes_bps),
                str(self.ci_low_bps), str(self.ci_high_bps), str(self.samples),
                _q(self.input_hash), str(self.computed_at)]
        return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(vals)});"


class MarketIndexSink(Protocol):
    def record(self, row: MarketIndexRow) -> None: ...


class LogMarketIndexSink:
    """Collects the ``markets`` INSERTs it would send (dev/CI/dry-run). The default
    sink, so the relayer's indexing is fully exercised and testable without a chain;
    a signed registry sink (like the resolver's ``RegistryTablelandMutator``) is the
    live swap-in."""

    def __init__(self, table: str = DEFAULT_MARKETS_TABLE,
                 predictions_table: str = DEFAULT_PREDICTIONS_TABLE):
        self.table = table
        self.predictions_table = predictions_table
        self.rows: List[MarketIndexRow] = []
        self.predictions: List[PredictionIndexRow] = []
        self.statements: List[str] = []

    def record(self, row: MarketIndexRow) -> None:
        self.rows.append(row)
        stmt = row.sql(self.table)
        self.statements.append(stmt)
        logger.info("markets index <- %s", stmt)

    def record_prediction(self, row: PredictionIndexRow) -> None:
        self.predictions.append(row)
        stmt = row.sql(self.predictions_table)
        self.statements.append(stmt)
        logger.info("predictions index <- %s", stmt)
