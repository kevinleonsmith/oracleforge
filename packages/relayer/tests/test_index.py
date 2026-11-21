"""Markets-index row builder tests — the markets write is pure up to the signed tx."""
import json
import os
import sys
import unittest

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..")))

from oracleforge_relayer.chain import DryRunChain  # noqa: E402
from oracleforge_relayer.feeds import FeedRegistry  # noqa: E402
from oracleforge_relayer.index import (  # noqa: E402
    LogMarketIndexSink,
    MarketIndexRow,
)
from oracleforge_relayer.mapping import (  # noqa: E402
    build_categorical_create_market_args,
    build_create_market_args,
    build_scalar_create_market_args,
)
from oracleforge_relayer.relayer import Relayer  # noqa: E402

NOW = 1_737_010_000

BINARY_PROPOSAL = {
    "question": "Will EUR/USD close at or above 1.10 at market settlement?",
    "category": "MACRO", "close_at": NOW + 30 * 86400, "priors": [0.4],
    "oracle": {"feed": "EUR/USD", "threshold": 110_000_000, "comparator": 0,
               "fallback_feed": None, "max_stale": 3600},
}
SCALAR_PROPOSAL = {
    "question": "Where will ETH close at the end of the quarter?",
    "category": "CRYPTO", "close_at": NOW + 30 * 86400,
    "band": {"lower": 3000, "upper": 5000, "unit": "$"},
    "oracle": {"feed": "ETH/USD", "target_decimals": 0, "fallback_feed": None, "max_stale": 3600},
}
CATEGORICAL_PROPOSAL = {
    "question": "Which team wins the championship?",
    "category": "SPORTS", "close_at": NOW + 30 * 86400,
    "outcomes": ["Home", "Away", "Draw"],
    "oracle": {"feed": "FUNCTIONS/SPORTS", "fallback_feed": None, "max_stale": 3600},
}


class MarketIndexRowTests(unittest.TestCase):
    def setUp(self):
        self.reg = FeedRegistry()

    def test_binary_row_is_self_describing(self):
        args = build_create_market_args(BINARY_PROPOSAL, 6700, 10200, self.reg, NOW)
        row = MarketIndexRow.from_binary(args, category="MACRO", created_at=NOW)
        self.assertEqual(row.market_type, "binary")
        self.assertEqual(row.params, "{}")
        self.assertEqual(row.ai_prob_bps, 6700)
        self.assertEqual(row.market_id, args.market_id)
        sql = row.sql()
        self.assertTrue(sql.startswith("INSERT INTO markets ("))
        self.assertIn("market_id, question, question_hash, category, market_type, params, ai_prob_bps, created_at, close_at", sql)
        self.assertIn("'binary'", sql)
        self.assertIn("'MACRO'", sql)

    def test_scalar_params_carry_the_band_and_unit(self):
        args = build_scalar_create_market_args(SCALAR_PROPOSAL, 10200, self.reg, NOW)
        row = MarketIndexRow.from_scalar(args, category="CRYPTO", unit="$", created_at=NOW)
        self.assertEqual(row.market_type, "scalar")
        self.assertEqual(row.ai_prob_bps, 0)  # not a committed-probability market
        params = json.loads(row.params)
        self.assertEqual(params["lower"], 3000)
        self.assertEqual(params["upper"], 5000)
        self.assertEqual(params["unit"], "$")
        self.assertEqual(params["feed"], args.feed)  # feed label carried for the catalog
        self.assertIn("'scalar'", row.sql())

    def test_categorical_params_carry_outcome_labels(self):
        args = build_categorical_create_market_args(CATEGORICAL_PROPOSAL, 10200, self.reg, NOW)
        row = MarketIndexRow.from_categorical(
            args, category="SPORTS", outcomes=["Home", "Away", "Draw"], created_at=NOW)
        self.assertEqual(row.market_type, "categorical")
        params = json.loads(row.params)
        self.assertEqual(params["outcome_count"], 3)
        self.assertEqual(params["outcomes"], ["Home", "Away", "Draw"])
        self.assertIn("'categorical'", row.sql())

    def test_categorical_without_labels_still_carries_count(self):
        args = build_categorical_create_market_args(CATEGORICAL_PROPOSAL, 10200, self.reg, NOW)
        row = MarketIndexRow.from_categorical(args, outcomes=None)
        params = json.loads(row.params)
        self.assertEqual(params, {"feed": args.feed, "outcome_count": 3})

    def test_sql_escapes_single_quotes(self):
        args = build_create_market_args(BINARY_PROPOSAL, 6700, 10200, self.reg, NOW)
        row = MarketIndexRow.from_binary(args, category="MACRO")
        row.question = "O'Brien wins?"
        self.assertIn("'O''Brien wins?'", row.sql())

    def test_custom_table_name(self):
        args = build_create_market_args(BINARY_PROPOSAL, 6700, 10200, self.reg, NOW)
        sql = MarketIndexRow.from_binary(args).sql("markets_100_7")
        self.assertIn("INSERT INTO markets_100_7 (", sql)

    def test_log_sink_collects_rows_and_statements(self):
        sink = LogMarketIndexSink()
        args = build_create_market_args(BINARY_PROPOSAL, 6700, 10200, self.reg, NOW)
        sink.record(MarketIndexRow.from_binary(args))
        self.assertEqual(len(sink.rows), 1)
        self.assertEqual(len(sink.statements), 1)
        self.assertIn("INSERT INTO markets", sink.statements[0])


class RelayerIndexingTests(unittest.TestCase):
    """The relayer records a markets-index row for each freshly-created market."""

    def _relayer(self):
        sink = LogMarketIndexSink()
        chain = DryRunChain(chain_id=10200)
        return Relayer(chain, FeedRegistry(), now_ts_fn=lambda: NOW, index_sink=sink), sink

    def test_binary_submit_records_index_row(self):
        relayer, sink = self._relayer()
        res = relayer.relay_one(BINARY_PROPOSAL)
        self.assertEqual(res.status, "submitted")
        self.assertEqual(len(sink.rows), 1)
        self.assertEqual(sink.rows[0].market_type, "binary")
        self.assertEqual(sink.rows[0].market_id, res.market_id)

    def test_scalar_submit_records_index_row(self):
        relayer, sink = self._relayer()
        res = relayer.relay_scalar_one(SCALAR_PROPOSAL)
        self.assertEqual(res.status, "submitted")
        self.assertEqual(sink.rows[0].market_type, "scalar")
        self.assertEqual(json.loads(sink.rows[0].params)["unit"], "$")

    def test_categorical_submit_records_index_row(self):
        relayer, sink = self._relayer()
        res = relayer.relay_categorical_one(CATEGORICAL_PROPOSAL)
        self.assertEqual(res.status, "submitted")
        self.assertEqual(sink.rows[0].market_type, "categorical")
        self.assertEqual(json.loads(sink.rows[0].params)["outcomes"], ["Home", "Away", "Draw"])

    def test_skipped_proposal_records_no_row(self):
        relayer, sink = self._relayer()
        bad = {k: v for k, v in SCALAR_PROPOSAL.items() if k != "band"}
        res = relayer.relay_scalar_one(bad)
        self.assertEqual(res.status, "skipped")
        self.assertEqual(len(sink.rows), 0)


if __name__ == "__main__":
    unittest.main()
