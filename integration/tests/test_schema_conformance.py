"""Schema-conformance: the SQL the workers emit actually runs against the shared
schema.

Every package unit-tests its SQL builders at the *string* level, and the frontend
tests its query strings — but the two sides (the ``schema.sql`` table definitions
and the INSERT/UPDATE statements the relayer, resolver and archiver emit) are never
executed together, so a column rename or a type drift between them would slip past
all of those tests. This loads the real ``schema.sql`` into an in-memory SQLite
database and round-trips each worker's statements through it: the writes must apply
(columns exist, types fit) and read back as expected. SQLite is what Tableland runs,
so conformance here is conformance there.
"""
import os
import sqlite3
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
for _pkg in ("relayer", "resolver", "archiver"):
    _p = os.path.join(_ROOT, "packages", _pkg)
    if _p not in sys.path:
        sys.path.insert(0, _p)

SCHEMA_PATH = os.path.join(_ROOT, "packages", "shared", "tableland", "schema.sql")

from oracleforge_archiver.tableland import WriteBack  # noqa: E402
from oracleforge_relayer.feeds import FeedRegistry  # noqa: E402
from oracleforge_relayer.index import MarketIndexRow, PredictionIndexRow  # noqa: E402
from oracleforge_relayer.mapping import (  # noqa: E402
    build_categorical_create_market_args,
    build_create_market_args,
    build_scalar_create_market_args,
)
from oracleforge_resolver.archive import (  # noqa: E402
    MarketProposalUpdate,
    MarketStatusUpdate,
    OracleReportRow,
)
from oracleforge_resolver.models import OracleReport  # noqa: E402
from oracleforge_resolver.positions import (  # noqa: E402
    ClaimEvent,
    PositionClaimUpdate,
    PositionEvent,
    PositionRow,
)

NOW = 1_737_010_000
CHAIN = 10200


def _db() -> sqlite3.Connection:
    """A fresh in-memory DB with every table from the shared schema."""
    con = sqlite3.connect(":memory:")
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        con.executescript(fh.read())
    return con


class SchemaLoads(unittest.TestCase):
    def test_schema_executes_and_defines_the_core_tables(self):
        con = _db()
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertTrue({"markets", "oracle_reports", "predictions",
                         "governance_proposals"}.issubset(names))


class MarketsLifecycleConforms(unittest.TestCase):
    """create INSERT -> propose UPDATE -> settle UPDATE -> arweave back-fill, all
    through the real schema, for each market type."""

    def setUp(self):
        self.con = _db()
        self.reg = FeedRegistry()

    def _create(self, row: MarketIndexRow):
        self.con.execute(row.sql("markets"))

    def _row(self, market_id: str):
        self.con.row_factory = sqlite3.Row
        return self.con.execute(
            "SELECT * FROM markets WHERE market_id=?", (market_id,)).fetchone()

    def test_binary_market_full_lifecycle(self):
        args = build_create_market_args(
            {"question": "Will EUR/USD close >= 1.10?", "category": "MACRO",
             "close_at": NOW + 30 * 86400,
             "oracle": {"feed": "EUR/USD", "threshold": 110_000_000, "comparator": 0,
                        "fallback_feed": None, "max_stale": 3600}},
            6700, CHAIN, self.reg, NOW)
        mid = args.market_id
        self._create(MarketIndexRow.from_binary(args, category="MACRO", created_at=NOW))
        self.assertEqual(self._row(mid)["status"], "OPEN")  # schema default

        # propose -> CLOSED + proposed_at
        self.con.execute(MarketProposalUpdate(mid, NOW).sql("markets"))
        r = self._row(mid)
        self.assertEqual(r["status"], "CLOSED")
        self.assertEqual(r["proposed_at"], NOW)

        # settle -> RESOLVED + outcome
        report = OracleReport(market_id=mid, outcome=1, resolved_at=NOW, feed="EUR/USD")
        self.con.execute(MarketStatusUpdate.from_report(report).sql("markets"))
        r = self._row(mid)
        self.assertEqual(r["status"], "RESOLVED")
        self.assertEqual(r["outcome"], 1)

        # archiver back-fills arweave_tx
        self.con.execute(WriteBack("markets", "market_id", mid, "arweave_tx", "ar://xyz").sql())
        self.assertEqual(self._row(mid)["arweave_tx"], "ar://xyz")

    def test_scalar_market_row_and_void_settlement(self):
        args = build_scalar_create_market_args(
            {"question": "Where will ETH close?", "category": "CRYPTO",
             "close_at": NOW + 30 * 86400, "band": {"lower": 3000, "upper": 5000, "unit": "$"},
             "oracle": {"feed": "ETH/USD", "target_decimals": 0, "fallback_feed": None, "max_stale": 3600}},
            CHAIN, self.reg, NOW)
        mid = args.market_id
        self._create(MarketIndexRow.from_scalar(args, category="CRYPTO", unit="$", created_at=NOW))
        self.assertEqual(self._row(mid)["market_type"], "scalar")

        # a void settlement (outcome < 0) -> INVALID, outcome left null
        report = OracleReport(market_id=mid, outcome=-1, resolved_at=NOW, feed="ETH/USD", kind="scalar")
        self.con.execute(MarketStatusUpdate.from_report(report).sql("markets"))
        r = self._row(mid)
        self.assertEqual(r["status"], "INVALID")
        self.assertIsNone(r["outcome"])

    def test_categorical_market_row_and_settlement(self):
        args = build_categorical_create_market_args(
            {"question": "Which team wins?", "category": "SPORTS",
             "close_at": NOW + 30 * 86400, "outcomes": ["Home", "Away", "Draw"],
             "oracle": {"feed": "FUNCTIONS/SPORTS", "fallback_feed": None, "max_stale": 3600}},
            CHAIN, self.reg, NOW)
        mid = args.market_id
        self._create(MarketIndexRow.from_categorical(
            args, category="SPORTS", outcomes=["Home", "Away", "Draw"], created_at=NOW))
        self.assertEqual(self._row(mid)["market_type"], "categorical")

        # categorical settles to a winning index
        report = OracleReport(market_id=mid, outcome=2, resolved_at=NOW, feed="FUNCTIONS/SPORTS", kind="categorical")
        self.con.execute(MarketStatusUpdate.from_report(report).sql("markets"))
        r = self._row(mid)
        self.assertEqual(r["status"], "RESOLVED")
        self.assertEqual(r["outcome"], 2)  # winning outcome index


class OracleReportsConforms(unittest.TestCase):
    def setUp(self):
        self.con = _db()

    def test_report_insert_and_arweave_backfill(self):
        report = OracleReport(market_id="0xabc", outcome=1, resolved_at=NOW,
                              feed="EUR/USD", tx_hash="0xdead", answer=110_000_000, kind="binary")
        self.con.execute(OracleReportRow.from_report(report).sql("oracle_reports"))
        self.con.row_factory = sqlite3.Row
        row = self.con.execute(
            "SELECT * FROM oracle_reports WHERE market_id='0xabc'").fetchone()
        self.assertEqual(row["market_type"], "binary")
        self.assertEqual(row["outcome"], 1)
        self.assertEqual(row["answer"], "110000000")
        self.assertEqual(row["round_id"], "0xdead")

        self.con.execute(WriteBack("oracle_reports", "market_id", "0xabc", "arweave_tx", "ar://ev").sql())
        row = self.con.execute(
            "SELECT arweave_tx FROM oracle_reports WHERE market_id='0xabc'").fetchone()
        self.assertEqual(row["arweave_tx"], "ar://ev")

    def test_categorical_report_market_type_is_persisted(self):
        # the market_type column is what disambiguates outcome=0 across types
        report = OracleReport(market_id="0xc", outcome=0, resolved_at=NOW,
                              feed="FUNCTIONS/ELECTION", kind="categorical")
        self.con.execute(OracleReportRow.from_report(report).sql("oracle_reports"))
        self.con.row_factory = sqlite3.Row
        row = self.con.execute("SELECT market_type, outcome FROM oracle_reports WHERE market_id='0xc'").fetchone()
        self.assertEqual((row["market_type"], row["outcome"]), ("categorical", 0))


class PositionsConforms(unittest.TestCase):
    def setUp(self):
        self.con = _db()

    def test_position_row_inserts_against_schema(self):
        ev = PositionEvent.from_dict({
            "market_id": "0xMKT", "account": "0xAlice", "side": 1, "amount": 10 ** 24,
            "tx_hash": "0xdead", "created_at": NOW})
        self.con.execute(PositionRow.from_event(ev).sql("positions"))
        self.con.row_factory = sqlite3.Row
        r = self.con.execute("SELECT * FROM positions WHERE market_id='0xMKT'").fetchone()
        self.assertEqual(r["account"], "0xAlice")
        self.assertEqual(r["side"], 1)
        self.assertEqual(r["amount"], str(10 ** 24))  # uint256 round-trips as a string
        self.assertEqual(r["claimed"], 0)             # schema/default

        # a claim flips claimed to 1 for that account's positions in the market
        self.con.execute(
            PositionClaimUpdate.from_event(ClaimEvent("0xMKT", "0xAlice")).sql("positions"))
        r2 = self.con.execute("SELECT claimed FROM positions WHERE market_id='0xMKT'").fetchone()
        self.assertEqual(r2["claimed"], 1)


class PredictionsConforms(unittest.TestCase):
    def setUp(self):
        self.con = _db()

    def test_prediction_row_inserts_against_schema(self):
        notice = {"prob_bps": 6700, "ci_low_bps": 6100, "ci_high_bps": 7300,
                  "samples": 50000, "input_hash": "0xdef"}
        row = PredictionIndexRow.from_notice("0xMKT", notice, NOW)
        self.con.execute(row.sql("predictions"))
        self.con.row_factory = sqlite3.Row
        r = self.con.execute("SELECT * FROM predictions WHERE market_id='0xMKT'").fetchone()
        self.assertEqual(r["prob_yes_bps"], 6700)
        self.assertEqual((r["ci_low_bps"], r["ci_high_bps"]), (6100, 7300))
        self.assertEqual(r["samples"], 50000)
        self.assertEqual(r["model"], "forge-forecast-mc")


if __name__ == "__main__":
    unittest.main()
