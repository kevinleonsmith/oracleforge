"""End-to-end: live stdlib server + urllib client + generator over HTTP."""
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ai-market-generator")))

from oracleforge_inference.client import RemoteDrafter, RemoteEmbedder  # noqa: E402
from oracleforge_inference.server import make_server  # noqa: E402
from oracleforge_inference.service import build_engine  # noqa: E402


class ServerTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = make_server(build_engine(device="cpu"), host="127.0.0.1", port=0)
        cls.port = cls.srv.server_address[1]
        cls.url = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()


class EndToEndTests(ServerTestBase):
    def test_health(self):
        emb = RemoteEmbedder(self.url)
        self.assertEqual(emb.dim, 256)

    def test_remote_embed_matches_local_hashing(self):
        from oracleforge_ai.embeddings import HashingEmbedder

        remote = RemoteEmbedder(self.url).embed("fed signals a rate cut")
        local = HashingEmbedder().embed("fed signals a rate cut")
        self.assertEqual(remote, local)  # service wraps the same embedder

    def test_remote_draft(self):
        q = RemoteDrafter(self.url).draft("eu-fx", ["EUR/USD near 1.10"], "MACRO")
        self.assertIn("EUR/USD", q)

    def test_bad_request_returns_400(self):
        req = urllib.request.Request(
            self.url + "/embed", data=b'{"texts": 123}',
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req)
        self.assertEqual(ctx.exception.code, 400)

    def test_generator_runs_over_remote_embedder(self):
        from oracleforge_ai import MarketGenerator

        gen = MarketGenerator(embedder=RemoteEmbedder(self.url))
        proposals = gen.propose()
        self.assertGreaterEqual(len(proposals), 1)
        # identical clustering to the local embedder -> same market set
        local = MarketGenerator().propose()
        self.assertEqual(
            sorted(p.question for p in proposals), sorted(p.question for p in local)
        )


if __name__ == "__main__":
    unittest.main()
