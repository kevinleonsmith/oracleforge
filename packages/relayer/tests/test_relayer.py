"""Mapping + orchestration tests (pure, no chain/network)."""
import os
import sys
import unittest

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..")))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "ai-market-generator")))

from oracleforge_relayer.chain import DryRunChain  # noqa: E402
from oracleforge_relayer.feeds import FeedRegistry  # noqa: E402
from oracleforge_relayer.mapping import SkipProposal, build_create_market_args  # noqa: E402
from oracleforge_relayer.relayer import Relayer  # noqa: E402

NOW = 1_737_010_000

BASE_PROPOSAL = {
    "question": "Will EUR/USD close at or above 1.10 at market settlement?",
    "category": "MACRO",
    "close_at": NOW + 30 * 86400,
    "priors": [0.4],  # committed prob is derived from these, not hand-set
    "oracle": {"feed": "EUR/USD", "threshold": 110_000_000, "comparator": 0,
               "fallback_feed": None, "max_stale": 3600},
}


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.reg = FeedRegistry()

    def test_builds_valid_args(self):
        args = build_create_market_args(BASE_PROPOSAL, 6700, 10200, self.reg, NOW)
        self.assertEqual(args.ai_prob_bps, 6700)  # committed value wins
        self.assertTrue(args.question_hash.startswith("0x"))
        self.assertEqual(len(args.oracle_params) - 2, 320)  # 160 bytes
        self.assertTrue(args.market_id.startswith("0x"))
        self.assertEqual(args.as_tx_args()[0], args.question_hash)

    def test_unknown_feed_skips(self):
        p = {**BASE_PROPOSAL, "oracle": {**BASE_PROPOSAL["oracle"], "feed": "MYSTERY/FEED"}}
        with self.assertRaises(SkipProposal):
            build_create_market_args(p, 5000, 10200, self.reg, NOW)

    def test_past_close_skips(self):
        p = {**BASE_PROPOSAL, "close_at": NOW - 10}
        with self.assertRaises(SkipProposal):
            build_create_market_args(p, 5000, 10200, self.reg, NOW)

    def test_prob_out_of_range_skips(self):
        with self.assertRaises(SkipProposal):
            build_create_market_args(BASE_PROPOSAL, 10_001, 10200, self.reg, NOW)


class OrchestrationTests(unittest.TestCase):
    def _relayer(self):
        chain = DryRunChain(chain_id=10200)
        return Relayer(chain, FeedRegistry(), now_ts_fn=lambda: NOW), chain

    def test_dry_run_submits_committed_forecast(self):
        from oracleforge_relayer.notices import StubNoticeSource
        from oracleforge_relayer.relayer import proposal_to_request

        relayer, chain = self._relayer()
        [res] = relayer.run([BASE_PROPOSAL])
        self.assertEqual(res.status, "submitted")
        self.assertEqual(len(chain.submitted), 1)
        # the value submitted is exactly the committed (stub) forecast for the request
        expected = StubNoticeSource().forecast(proposal_to_request(BASE_PROPOSAL))["prob_bps"]
        self.assertEqual(res.ai_prob_bps, expected)

    def test_idempotent_second_run_sees_exists(self):
        relayer, chain = self._relayer()
        relayer.run([BASE_PROPOSAL])
        [res2] = relayer.run([BASE_PROPOSAL])
        self.assertEqual(res2.status, "exists")
        self.assertEqual(len(chain.submitted), 1)  # not resubmitted

    def test_unauthorized_relayer_raises(self):
        class NotRelayer(DryRunChain):
            def is_relayer(self):
                return False

        relayer = Relayer(NotRelayer(chain_id=10200), FeedRegistry(), now_ts_fn=lambda: NOW)
        with self.assertRaises(PermissionError):
            relayer.run([BASE_PROPOSAL])

    def test_full_generator_batch_relays(self):
        from oracleforge_ai import MarketGenerator

        proposals = [p.to_dict() for p in MarketGenerator().propose()]
        relayer, chain = self._relayer()
        results = relayer.run(proposals)
        self.assertEqual(len(results), len(proposals))
        # every proposal either submitted or was skipped for a named reason
        self.assertTrue(all(r.status in ("submitted", "skipped", "exists") for r in results))
        self.assertGreaterEqual(sum(1 for r in results if r.status == "submitted"), 1)
        # determinism invariant: committed (stub) prob == generator's local prob
        local = {p["question"]: p["ai_prob_bps"] for p in proposals}
        for r in results:
            if r.status == "submitted":
                self.assertEqual(r.ai_prob_bps, local[r.question])


if __name__ == "__main__":
    unittest.main()
