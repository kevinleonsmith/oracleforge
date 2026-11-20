"""Archiver orchestration tests against the local content-addressed store."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from oracleforge_archiver.archiver import (Archiver, artifact_from_market,  # noqa: E402
                                           artifact_from_oracle_report)
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


if __name__ == "__main__":
    unittest.main()
