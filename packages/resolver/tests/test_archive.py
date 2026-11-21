"""Report-sink tests — the oracle_reports write-back is pure up to the signed tx."""
import os
import sys
import unittest

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..")))

from oracleforge_resolver.archive import (  # noqa: E402
    LogReportSink,
    LogTablelandMutator,
    MarketProposalUpdate,
    MarketStatusUpdate,
    OracleReportRow,
    RegistryTablelandMutator,
    TablelandReportSink,
)
from oracleforge_resolver.models import OracleReport  # noqa: E402


def _binary_report(**over):
    base = dict(market_id="0xabc", outcome=1, resolved_at=1_737_000_000,
                feed="EUR/USD", tx_hash="", answer=110_000_000, kind="binary")
    base.update(over)
    return OracleReport(**base)


class OracleReportRowTests(unittest.TestCase):
    def test_maps_binary_report_to_row(self):
        row = OracleReportRow.from_report(_binary_report())
        self.assertEqual(row.market_id, "0xabc")
        self.assertEqual(row.feed, "EUR/USD")
        self.assertEqual(row.answer, "110000000")   # raw oracle answer, as string
        self.assertEqual(row.outcome, 1)
        self.assertEqual(row.reported_at, 1_737_000_000)
        self.assertIsNone(row.round_id)             # no tx_hash -> omitted

    def test_scalar_report_stores_value_as_answer(self):
        # scalar: answer carries the settled value, outcome is unused (0)
        row = OracleReportRow.from_report(
            _binary_report(kind="scalar", outcome=0, answer=4200, feed="ETH/USD"))
        self.assertEqual(row.answer, "4200")
        self.assertEqual(row.outcome, 0)

    def test_market_type_is_persisted_per_kind(self):
        # the report's kind lands in the self-describing market_type column
        for kind in ("binary", "scalar", "categorical"):
            row = OracleReportRow.from_report(_binary_report(kind=kind))
            self.assertEqual(row.market_type, kind)
            self.assertIn(f"'{kind}'", row.sql())

    def test_market_type_disambiguates_outcome_zero(self):
        # outcome=0 means NO for binary but "outcome 0 won" for categorical; the
        # market_type column is the only thing that tells them apart.
        binary0 = OracleReportRow.from_report(_binary_report(kind="binary", outcome=0))
        cat0 = OracleReportRow.from_report(
            _binary_report(kind="categorical", outcome=0, answer=None, feed="FUNCTIONS/ELECTION"))
        self.assertEqual(binary0.outcome, cat0.outcome)        # same raw outcome
        self.assertNotEqual(binary0.market_type, cat0.market_type)  # disambiguated
        self.assertIn("'binary'", binary0.sql())
        self.assertIn("'categorical'", cat0.sql())

    def test_market_type_defaults_to_binary(self):
        # a row built directly (not from a report) keeps the back-compatible default
        row = OracleReportRow(market_id="0x1", feed="f", answer="1", outcome=1, reported_at=0)
        self.assertEqual(row.market_type, "binary")

    def test_none_answer_becomes_empty_string_not_null(self):
        # oracle_reports.answer is NOT NULL — a missing answer must still be a value
        row = OracleReportRow.from_report(_binary_report(answer=None))
        self.assertEqual(row.answer, "")

    def test_negative_outcome_for_voided_market(self):
        row = OracleReportRow.from_report(_binary_report(outcome=-1, answer=None))
        self.assertIn("-1", row.sql())

    def test_sql_has_expected_columns_and_values(self):
        row = OracleReportRow.from_report(_binary_report())
        sql = row.sql()
        self.assertTrue(sql.startswith("INSERT INTO oracle_reports ("))
        self.assertTrue(sql.endswith(");"))
        # column order and the defaulted creation-time columns
        self.assertIn("market_id, market_type, feed, answer, comparator, threshold, outcome, reported_at", sql)
        self.assertIn("'0xabc'", sql)
        self.assertIn("'binary'", sql)            # self-describing market_type
        self.assertIn("'EUR/USD'", sql)
        self.assertIn("'110000000'", sql)
        self.assertIn("0, ''", sql)               # comparator default 0, threshold default ''
        self.assertNotIn("round_id", sql)         # omitted when absent
        self.assertNotIn(" id,", sql)             # id auto-assigned, never written

    def test_round_id_included_when_tx_hash_present(self):
        row = OracleReportRow.from_report(_binary_report(tx_hash="0xdeadbeef"))
        self.assertEqual(row.round_id, "0xdeadbeef")
        self.assertIn("round_id", row.sql())
        self.assertIn("'0xdeadbeef'", row.sql())

    def test_custom_table_name(self):
        sql = OracleReportRow.from_report(_binary_report()).sql("reports_42")
        self.assertIn("INSERT INTO reports_42 (", sql)

    def test_sql_escapes_single_quotes(self):
        # a feed with an apostrophe must not break out of the string literal
        row = OracleReportRow.from_report(_binary_report(feed="O'Brien/USD"))
        self.assertIn("'O''Brien/USD'", row.sql())


class MarketStatusUpdateTests(unittest.TestCase):
    def test_resolved_sets_status_and_outcome(self):
        u = MarketStatusUpdate.from_report(_binary_report(outcome=1))
        self.assertEqual(u.status, "RESOLVED")
        self.assertEqual(u.outcome, 1)
        sql = u.sql()
        self.assertEqual(sql, "UPDATE markets SET status='RESOLVED', outcome=1 WHERE market_id='0xabc';")

    def test_void_sets_invalid_and_omits_outcome(self):
        u = MarketStatusUpdate.from_report(_binary_report(outcome=-1))
        self.assertEqual(u.status, "INVALID")
        self.assertIsNone(u.outcome)
        sql = u.sql()
        self.assertIn("SET status='INVALID'", sql)
        self.assertNotIn("outcome", sql)  # a void leaves outcome unset

    def test_categorical_resolved_records_winning_index(self):
        u = MarketStatusUpdate.from_report(_binary_report(kind="categorical", outcome=2))
        self.assertEqual(u.status, "RESOLVED")
        self.assertEqual(u.outcome, 2)  # winning outcome index

    def test_custom_markets_table(self):
        sql = MarketStatusUpdate.from_report(_binary_report()).sql("markets_100_7")
        self.assertIn("UPDATE markets_100_7 SET", sql)


class MarketProposalUpdateTests(unittest.TestCase):
    def test_propose_sets_closed_and_proposed_at(self):
        sql = MarketProposalUpdate(market_id="0xabc", proposed_at=1_737_000_000).sql()
        self.assertEqual(
            sql,
            "UPDATE markets SET status='CLOSED', proposed_at=1737000000 "
            "WHERE market_id='0xabc';",
        )

    def test_custom_markets_table(self):
        sql = MarketProposalUpdate("0x1", 5).sql("markets_100_7")
        self.assertIn("UPDATE markets_100_7 SET status='CLOSED'", sql)


class TablelandReportSinkTests(unittest.TestCase):
    def test_record_emits_both_insert_and_update(self):
        mutator = LogTablelandMutator()
        sink = TablelandReportSink(mutator=mutator)
        sink.record(_binary_report())
        self.assertEqual(len(sink.rows), 1)
        self.assertEqual(len(sink.updates), 1)
        # one INSERT (evidence) + one UPDATE (catalog transition)
        self.assertEqual(len(mutator.statements), 2)
        self.assertIn("INSERT INTO oracle_reports", mutator.statements[0])
        self.assertIn("UPDATE markets SET status='RESOLVED'", mutator.statements[1])

    def test_void_report_updates_markets_to_invalid(self):
        mutator = LogTablelandMutator()
        sink = TablelandReportSink(mutator=mutator)
        sink.record(_binary_report(outcome=-1, answer=None))
        self.assertIn("UPDATE markets SET status='INVALID'", mutator.statements[1])

    def test_record_proposal_emits_closed_update(self):
        mutator = LogTablelandMutator()
        sink = TablelandReportSink(mutator=mutator)
        sink.record_proposal("0xabc", 1_737_000_000)
        self.assertEqual(len(sink.proposals), 1)
        self.assertEqual(len(mutator.statements), 1)
        self.assertIn("UPDATE markets SET status='CLOSED', proposed_at=1737000000", mutator.statements[0])

    def test_log_sink_record_proposal_collects_in_memory(self):
        sink = LogReportSink()
        sink.record_proposal("0x1", 42)
        self.assertEqual(sink.proposals, [("0x1", 42)])

    def test_default_mutator_is_log(self):
        sink = TablelandReportSink()
        sink.record(_binary_report())
        self.assertIsInstance(sink.mutator, LogTablelandMutator)
        self.assertEqual(len(sink.mutator.statements), 2)

    def test_multiple_records_accumulate(self):
        sink = TablelandReportSink()
        sink.record(_binary_report(market_id="0x1"))
        sink.record(_binary_report(market_id="0x2"))
        self.assertEqual([r.market_id for r in sink.rows], ["0x1", "0x2"])
        self.assertEqual([u.market_id for u in sink.updates], ["0x1", "0x2"])
        self.assertEqual(len(sink.mutator.statements), 4)  # 2 per settlement

    def test_custom_table_flows_into_sql(self):
        sink = TablelandReportSink(table="oracle_reports_100_7")
        sink.record(_binary_report())
        self.assertIn("INSERT INTO oracle_reports_100_7 (", sink.mutator.statements[0])

    def test_is_a_report_sink(self):
        # duck-types the ReportSink protocol like LogReportSink
        for sink in (LogReportSink(), TablelandReportSink()):
            sink.record(_binary_report())


class RegistryTablelandMutatorTests(unittest.TestCase):
    def test_live_mutate_not_implemented_but_carries_statement(self):
        m = RegistryTablelandMutator("http://rpc", "0xReg", 7, 10200, "0xpk")
        with self.assertRaises(NotImplementedError) as ctx:
            m.mutate("INSERT INTO oracle_reports (market_id) VALUES ('0xabc');")
        self.assertIn("oracle_reports", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
