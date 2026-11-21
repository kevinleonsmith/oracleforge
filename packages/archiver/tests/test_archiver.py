"""Archiver orchestration tests against the local content-addressed store."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from oracleforge_archiver.archiver import (Archiver, artifact_from_governance,  # noqa: E402
                                           artifact_from_market,
                                           artifact_from_oracle_report,
                                           artifact_from_prediction,
                                           artifact_from_simulation)
from oracleforge_archiver.arweave import LocalArweaveClient  # noqa: E402
from oracleforge_archiver.canonical import content_hash  # noqa: E402
from oracleforge_archiver.models import Artifact, ArtifactKind  # noqa: E402
from oracleforge_archiver.sinks import ArweaveReportSink  # noqa: E402
from oracleforge_archiver.tableland import LogTablelandWriter  # noqa: E402

MARKET = {
    "market_id": "0xa7f3", "question": "Will US CPI print below 2.6% YoY?",
    "category": "MACRO", "close_at": 1740800000, "evidence": ["sig a", "sig b"],
}


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="arw-test-")
        self.client = LocalArweaveClient(self.tmp)
        self.writer = LogTablelandWriter()
        self.archiver = Archiver(self.client, self.writer, now_fn=lambda: 1_740_000_000)

    def test_archive_returns_receipt_and_stores_data(self):
        r = self.archiver.archive(artifact_from_market(MARKET))
        self.assertFalse(r.deduped)
        self.assertEqual(r.content_hash, content_hash(MARKET))
        self.assertTrue(r.written_back)
        # the stored bytes round-trip and still match the content hash
        stored = self.client.get(r.tx_id)
        self.assertEqual("0x" + __import__("hashlib").sha256(stored).hexdigest(), r.content_hash)

    def test_dedupe_on_identical_payload(self):
        r1 = self.archiver.archive(artifact_from_market(MARKET))
        r2 = self.archiver.archive(artifact_from_market(dict(MARKET)))  # same data
        self.assertFalse(r1.deduped)
        self.assertTrue(r2.deduped)
        self.assertEqual(r1.tx_id, r2.tx_id)

    def test_dedupe_persists_across_client_instances(self):
        r1 = self.archiver.archive(artifact_from_market(MARKET))
        # a fresh client over the same dir must see the manifest and dedupe
        client2 = LocalArweaveClient(self.tmp)
        arch2 = Archiver(client2, now_fn=lambda: 1)
        r2 = arch2.archive(artifact_from_market(MARKET))
        self.assertTrue(r2.deduped)
        self.assertEqual(r2.tx_id, r1.tx_id)

    def test_writeback_targets_correct_row(self):
        self.archiver.archive(artifact_from_market(MARKET))
        wb = self.writer.writes[-1]
        self.assertEqual(wb.table, "markets")
        self.assertEqual(wb.id_column, "market_id")
        self.assertEqual(wb.row_id, "0xa7f3")
        self.assertIn("UPDATE markets SET arweave_tx=", wb.sql())

    def test_tags_include_type_and_hash(self):
        r = self.archiver.archive(artifact_from_market(MARKET))
        names = {t["name"]: t["value"] for t in r.tags}
        self.assertEqual(names["Type"], "market")
        self.assertEqual(names["Content-SHA256"], r.content_hash)
        self.assertEqual(names["App-Name"], "OracleForge")
        self.assertEqual(names["Market-Id"], "0xa7f3")

    def test_no_writer_means_no_writeback(self):
        arch = Archiver(self.client)  # writer=None
        r = arch.archive(artifact_from_market(MARKET))
        self.assertFalse(r.written_back)


class OracleReportSinkTests(unittest.TestCase):
    def test_sink_archives_report(self):
        tmp = tempfile.mkdtemp(prefix="arw-sink-")
        archiver = Archiver(LocalArweaveClient(tmp), LogTablelandWriter(), now_fn=lambda: 1)
        sink = ArweaveReportSink(archiver)

        class Report:  # duck-typed like the resolver's OracleReport
            market_id = "0xa7f3"; outcome = 1; resolved_at = 1740900000
            feed = "ECON/CPI"; tx_hash = "0xabc"; answer = 255

        sink.record(Report())
        self.assertEqual(len(sink.receipts), 1)
        self.assertEqual(sink.receipts[0].kind, "oracle-report")

    def test_report_from_dict(self):
        a = artifact_from_oracle_report({"market_id": "0x1", "outcome": 0, "resolved_at": 5})
        self.assertEqual(a.kind, ArtifactKind.ORACLE_REPORT)
        self.assertEqual(a.payload["outcome"], 0)
        self.assertEqual(a.payload["market_type"], "binary")  # defaults when absent

    def test_report_carries_market_type(self):
        # a categorical settlement's evidence bundle is self-describing: outcome 0
        # is the winning index, not a binary NO, and market_type says so.
        a = artifact_from_oracle_report(
            {"market_id": "0x1", "outcome": 0, "resolved_at": 5, "kind": "categorical"})
        self.assertEqual(a.payload["market_type"], "categorical")


class ArtifactBuilderTests(unittest.TestCase):
    """Each artifact kind targets the right Tableland table/row and carries its
    payload — the archiver stores and back-fills by these fields."""

    def test_market_artifact_targets_markets_row(self):
        a = artifact_from_market(MARKET)
        self.assertEqual(a.kind, ArtifactKind.MARKET)
        self.assertEqual((a.table, a.id_column, a.row_id), ("markets", "market_id", "0xa7f3"))
        self.assertEqual(a.extra_tags["Category"], "MACRO")

    def test_market_artifact_falls_back_to_question_hash(self):
        a = artifact_from_market({"question_hash": "0xqh", "category": "GEO"})
        self.assertEqual(a.row_id, "0xqh")  # no market_id yet -> question_hash

    def test_prediction_artifact_carries_the_confidence_interval(self):
        pred = {"market_id": "0xa7f3", "model": "forge-forecast-mc",
                "prob_yes_bps": 6700, "ci_low_bps": 6100, "ci_high_bps": 7300,
                "samples": 50000, "input_hash": "0xih"}
        a = artifact_from_prediction(pred)
        self.assertEqual(a.kind, ArtifactKind.PREDICTION)
        self.assertEqual((a.table, a.id_column, a.row_id), ("predictions", "market_id", "0xa7f3"))
        # the permanent record carries the full forecast, CI included
        self.assertEqual(a.payload["ci_low_bps"], 6100)
        self.assertEqual(a.payload["ci_high_bps"], 7300)
        self.assertEqual(a.extra_tags["Model"], "forge-forecast-mc")

    def test_governance_artifact_targets_proposal_row(self):
        a = artifact_from_governance({"proposal_id": "OFP-47", "title": "fund reserve"})
        self.assertEqual(a.kind, ArtifactKind.GOVERNANCE)
        self.assertEqual((a.table, a.id_column, a.row_id), ("governance_proposals", "proposal_id", "OFP-47"))
        self.assertEqual(a.extra_tags["Proposal-Id"], "OFP-47")

    def test_simulation_artifact_targets_simulation_row(self):
        a = artifact_from_simulation({"id": "sim-9", "market_id": "0xa7f3", "kind": "montecarlo"})
        self.assertEqual(a.kind, ArtifactKind.SIMULATION)
        self.assertEqual((a.table, a.id_column, a.row_id), ("simulations", "id", "sim-9"))

    def test_each_kind_is_content_addressed_independently(self):
        # same logical id, different payloads/kinds -> distinct content hashes, so
        # archiving one never dedupes against another.
        tmp = tempfile.mkdtemp(prefix="arw-kinds-")
        archiver = Archiver(LocalArweaveClient(tmp), LogTablelandWriter(), now_fn=lambda: 1)
        r_market = archiver.archive(artifact_from_market(MARKET))
        r_pred = archiver.archive(artifact_from_prediction(
            {"market_id": "0xa7f3", "model": "m", "prob_yes_bps": 1, "ci_low_bps": 0,
             "ci_high_bps": 2, "samples": 1, "input_hash": "0x"}))
        self.assertFalse(r_market.deduped)
        self.assertFalse(r_pred.deduped)
        self.assertNotEqual(r_market.content_hash, r_pred.content_hash)


if __name__ == "__main__":
    unittest.main()
