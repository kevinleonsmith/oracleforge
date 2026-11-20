"""Engine + schema tests (no server, no network)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ai-market-generator")))

from oracleforge_inference.schemas import DraftRequest, EmbedRequest  # noqa: E402
from oracleforge_inference.service import build_engine  # noqa: E402


class SchemaTests(unittest.TestCase):
    def test_embed_request_validation(self):
        self.assertEqual(EmbedRequest.from_dict({"texts": ["a", "b"]}).texts, ["a", "b"])
        with self.assertRaises(ValueError):
            EmbedRequest.from_dict({"texts": "notalist"})

    def test_draft_request_requires_topic(self):
        with self.assertRaises(ValueError):
            DraftRequest.from_dict({"signals": []})


class EngineTests(unittest.TestCase):
    def setUp(self):
        # no sentence-transformers here -> falls back to HashingEmbedder
        self.engine = build_engine(device="cpu")

    def test_health_reports_fallback(self):
        h = self.engine.health()
        self.assertEqual(h.status, "ok")
        self.assertEqual(h.embedder, "HashingEmbedder")
        self.assertFalse(h.gpu)
        self.assertEqual(h.dim, 256)

    def test_embed_shapes_and_determinism(self):
        r1 = self.engine.embed(EmbedRequest(texts=["fed cuts rates", "eth staking"]))
        r2 = self.engine.embed(EmbedRequest(texts=["fed cuts rates", "eth staking"]))
        self.assertEqual(len(r1.embeddings), 2)
        self.assertEqual(len(r1.embeddings[0]), r1.dim)
        self.assertEqual(r1.embeddings, r2.embeddings)  # deterministic

    def test_draft_returns_template_question(self):
        r = self.engine.draft(DraftRequest(topic="us-rates", signals=["CPI cooling"], category="MACRO"))
        self.assertIn("CPI", r.question)
        self.assertEqual(r.model, "template-v1")

    def test_draft_generic_fallback(self):
        r = self.engine.draft(DraftRequest(topic="solar-flare", signals=[]))
        self.assertTrue(r.question.endswith("by the settlement date?"))


if __name__ == "__main__":
    unittest.main()
