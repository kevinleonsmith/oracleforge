"""Stdlib unittest suite — runs with `python -m unittest` (no pip install)."""
import unittest

from oracleforge_ai import MarketGenerator
from oracleforge_ai.cartesi import bayesian_update, monte_carlo_forecast
from oracleforge_ai.clustering import cluster_signals, is_duplicate
from oracleforge_ai.embeddings import HashingEmbedder, cosine
from oracleforge_ai.confidence import aggregate, score_sources
from oracleforge_ai.signals import default_sources


class EmbeddingTests(unittest.TestCase):
    def test_deterministic_and_normalized(self):
        e = HashingEmbedder()
        a1, a2 = e.embed("fed cuts rates"), e.embed("fed cuts rates")
        self.assertEqual(a1, a2)  # deterministic
        self.assertAlmostEqual(cosine(a1, a2), 1.0, places=6)  # self-similarity

    def test_similar_more_than_unrelated(self):
        e = HashingEmbedder()
        base = e.embed("eth staking ratio rises")
        near = e.embed("ethereum staking ratio climbs higher")
        far = e.embed("atlantic hurricane season outlook")
        self.assertGreater(cosine(base, near), cosine(base, far))


class ClusteringTests(unittest.TestCase):
    def test_clusters_and_dedupe(self):
        e = HashingEmbedder()
        sigs = []
        for s in default_sources():
            sigs.extend(s.fetch())
        clusters = cluster_signals(sigs, e, threshold=0.5)
        self.assertGreaterEqual(len(clusters), 3)

        self.assertTrue(
            is_duplicate(
                "Will EUR/USD close at or above 1.10 at settlement?",
                ["Will EUR/USD close at or above 1.10 at market settlement?"],
                e,
            )
        )
        self.assertFalse(
            is_duplicate(
                "Will 4 Category-5 hurricanes form in the Atlantic?",
                ["Will EUR/USD close above 1.10?"],
                e,
            )
        )


class ForecastTests(unittest.TestCase):
    def test_monte_carlo_deterministic(self):
        a = monte_carlo_forecast("Will X happen?", [0.4], samples=20000)
        b = monte_carlo_forecast("Will X happen?", [0.4], samples=20000)
        self.assertEqual(a.prob_yes, b.prob_yes)  # reproducible across runs
        self.assertTrue(0 <= a.prob_bps <= 10000)

    def test_positive_prior_leans_yes(self):
        pos = monte_carlo_forecast("q", [0.8], samples=20000).prob_yes
        neg = monte_carlo_forecast("q", [-0.8], samples=20000).prob_yes
        self.assertGreater(pos, neg)

    def test_bayesian_update_moves_with_evidence(self):
        self.assertGreater(bayesian_update(0.5, 3.0), 0.5)
        self.assertLess(bayesian_update(0.5, 0.33), 0.5)


class ConfidenceTests(unittest.TestCase):
    def test_scores_in_range(self):
        sigs = default_sources()[0].fetch()
        scores = score_sources(sigs)
        for v in scores.values():
            self.assertTrue(0.0 <= v <= 1.0)
        self.assertTrue(0.0 <= aggregate(scores) <= 1.0)


class PipelineTests(unittest.TestCase):
    def test_propose_produces_valid_markets(self):
        proposals = MarketGenerator().propose()
        self.assertTrue(len(proposals) >= 1)
        for p in proposals:
            self.assertTrue(0 <= p.ai_prob_bps <= 10000)
            self.assertTrue(0.0 <= p.confidence <= 1.0)
            self.assertIsNotNone(p.oracle)
            self.assertTrue(p.question_hash.startswith("0x"))
        # sorted by confidence descending
        confs = [p.confidence for p in proposals]
        self.assertEqual(confs, sorted(confs, reverse=True))

    def test_no_duplicate_questions(self):
        proposals = MarketGenerator().propose()
        qs = [p.question for p in proposals]
        self.assertEqual(len(qs), len(set(qs)))


if __name__ == "__main__":
    unittest.main()
