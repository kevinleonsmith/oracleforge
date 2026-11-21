"""Positions indexer tests — the positions write is pure up to the signed tx."""
import os
import sys
import unittest

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..")))

from oracleforge_resolver.archive import LogTablelandMutator  # noqa: E402
from oracleforge_resolver.positions import (  # noqa: E402
    ChainPositionEventSource,
    PositionEvent,
    PositionIndexer,
    PositionRow,
    StubPositionEventSource,
)


def _event(**over):
    base = dict(market_id="0xabc", account="0xAlice", side=1, amount=600,
                tx_hash="0xdead", created_at=1_737_000_000)
    base.update(over)
    return PositionEvent.from_dict(base)


class PositionRowTests(unittest.TestCase):
    def test_sql_columns_and_values(self):
        row = PositionRow.from_event(_event())
        sql = row.sql()
        self.assertTrue(sql.startswith("INSERT INTO positions ("))
        self.assertIn("market_id, account, side, amount, claimed, tx_hash, created_at", sql)
        self.assertIn("'0xabc'", sql)
        self.assertIn("'0xAlice'", sql)
        self.assertIn("'600'", sql)              # amount is a quoted decimal string (uint256)
        self.assertIn("'0xAlice', 1, '600', 0,", sql)  # side=1, then amount, then claimed=0

    def test_amount_is_quoted_decimal_string(self):
        # a 256-bit amount must survive as a string, not an int literal
        big = 10 ** 30
        row = PositionRow.from_event(_event(amount=big))
        self.assertIn(f"'{big}'", row.sql())

    def test_side_generalises_across_engines(self):
        # categorical outcome index 2 rides the same integer column
        row = PositionRow.from_event(_event(side=2))
        self.assertEqual(row.side, 2)
        self.assertIn("'0xAlice', 2, '600', 0,", row.sql())

    def test_sql_escapes_single_quotes(self):
        row = PositionRow.from_event(_event(account="0x'; DROP"))
        self.assertIn("'0x''; DROP'", row.sql())

    def test_custom_table(self):
        self.assertIn("INSERT INTO positions_100_7 (", PositionRow.from_event(_event()).sql("positions_100_7"))


class PositionIndexerTests(unittest.TestCase):
    def test_indexes_each_event_through_the_mutator(self):
        mutator = LogTablelandMutator()
        src = StubPositionEventSource([
            _event(account="0xAlice", side=1, amount=600),
            _event(account="0xBob", side=0, amount=400),
        ])
        idx = PositionIndexer(src, mutator=mutator)
        rows = idx.index()
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(mutator.statements), 2)
        self.assertEqual([r.account for r in rows], ["0xAlice", "0xBob"])
        self.assertTrue(all("INSERT INTO positions" in s for s in mutator.statements))

    def test_empty_source_writes_nothing(self):
        idx = PositionIndexer(StubPositionEventSource([]))
        self.assertEqual(idx.index(), [])

    def test_default_mutator_is_log(self):
        idx = PositionIndexer(StubPositionEventSource([_event()]))
        idx.index()
        self.assertIsInstance(idx.mutator, LogTablelandMutator)
        self.assertEqual(len(idx.mutator.statements), 1)

    def test_chain_source_is_the_unexercised_live_seam(self):
        src = ChainPositionEventSource("http://rpc", "0xEngine", 100)
        with self.assertRaises(NotImplementedError):
            src.events()


if __name__ == "__main__":
    unittest.main()
