"""Mapping + orchestration tests (pure, no chain/network)."""
import os
import sys
import unittest

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..")))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..", "ai-market-generator")))

from oracleforge_relayer.chain import DryRunChain  # noqa: E402
from oracleforge_relayer.feeds import FeedRegistry  # noqa: E402
from oracleforge_relayer.mapping import (  # noqa: E402
    SkipProposal,
    build_categorical_create_market_args,
    build_create_market_args,
    build_scalar_create_market_args,
)
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


class HardeningTests(unittest.TestCase):
    """Malformed proposals must SKIP (not raise a generic batch error) and never
    produce an out-of-range createMarket call."""

    def setUp(self):
        self.reg = FeedRegistry()

    def _o(self, **over):
        return {**BASE_PROPOSAL, "oracle": {**BASE_PROPOSAL["oracle"], **over}}

    def test_bad_comparator_skips(self):
        with self.assertRaises(SkipProposal):
            build_create_market_args(self._o(comparator=5), 5000, 10200, self.reg, NOW)

    def test_missing_threshold_skips(self):
        o = {k: v for k, v in BASE_PROPOSAL["oracle"].items() if k != "threshold"}
        p = {**BASE_PROPOSAL, "oracle": o}
        with self.assertRaises(SkipProposal):
            build_create_market_args(p, 5000, 10200, self.reg, NOW)

    def test_threshold_out_of_int256_skips(self):
        with self.assertRaises(SkipProposal):
            build_create_market_args(self._o(threshold=1 << 256), 5000, 10200, self.reg, NOW)

    def test_close_at_out_of_uint64_skips(self):
        p = {**BASE_PROPOSAL, "close_at": 1 << 64}
        with self.assertRaises(SkipProposal):
            build_create_market_args(p, 5000, 10200, self.reg, NOW)

    def test_nonint_close_at_skips(self):
        p = {**BASE_PROPOSAL, "close_at": "soon"}
        with self.assertRaises(SkipProposal):
            build_create_market_args(p, 5000, 10200, self.reg, NOW)

    def test_bad_max_stale_skips(self):
        with self.assertRaises(SkipProposal):
            build_create_market_args(self._o(max_stale=1 << 64), 5000, 10200, self.reg, NOW)


SCALAR_PROPOSAL = {
    "question": "Where will ETH close at the end of the quarter?",
    "category": "CRYPTO",
    "close_at": NOW + 30 * 86400,
    "band": {"lower": 3000, "upper": 5000},
    "oracle": {"feed": "ETH/USD", "target_decimals": 0, "fallback_feed": None, "max_stale": 3600},
}


class ScalarMappingTests(unittest.TestCase):
    def setUp(self):
        self.reg = FeedRegistry()

    def test_builds_valid_scalar_args(self):
        args = build_scalar_create_market_args(SCALAR_PROPOSAL, 10200, self.reg, NOW)
        self.assertEqual(args.lower, 3000)
        self.assertEqual(args.upper, 5000)
        self.assertEqual(len(args.oracle_params) - 2, 256)  # 128 bytes
        self.assertEqual(len(args.as_tx_args()), 5)
        self.assertEqual(args.as_tx_args()[2], 3000)  # lower in positional args
        self.assertTrue(args.market_id.startswith("0x"))

    def test_scalar_market_id_matches_binary_derivation(self):
        # same keccak(questionHash, closeAt, chainId) -> dedupe is cross-consistent
        from oracleforge_relayer import abi
        args = build_scalar_create_market_args(SCALAR_PROPOSAL, 10200, self.reg, NOW)
        qh = abi.question_hash(SCALAR_PROPOSAL["question"])
        self.assertEqual(args.market_id, abi.market_id(qh, SCALAR_PROPOSAL["close_at"], 10200))

    def test_inverted_band_skips(self):
        p = {**SCALAR_PROPOSAL, "band": {"lower": 5000, "upper": 3000}}
        with self.assertRaises(SkipProposal):
            build_scalar_create_market_args(p, 10200, self.reg, NOW)

    def test_missing_band_skips(self):
        p = {k: v for k, v in SCALAR_PROPOSAL.items() if k != "band"}
        with self.assertRaises(SkipProposal):
            build_scalar_create_market_args(p, 10200, self.reg, NOW)

    def test_unknown_feed_skips(self):
        p = {**SCALAR_PROPOSAL, "oracle": {**SCALAR_PROPOSAL["oracle"], "feed": "MYSTERY"}}
        with self.assertRaises(SkipProposal):
            build_scalar_create_market_args(p, 10200, self.reg, NOW)

    def test_excessive_target_decimals_skips(self):
        p = {**SCALAR_PROPOSAL, "oracle": {**SCALAR_PROPOSAL["oracle"], "target_decimals": 37}}
        with self.assertRaises(SkipProposal):
            build_scalar_create_market_args(p, 10200, self.reg, NOW)


CATEGORICAL_PROPOSAL = {
    "question": "Which team wins the championship?",
    "category": "SPORTS",
    "close_at": NOW + 30 * 86400,
    "outcomes": ["Home", "Away", "Draw"],
    "oracle": {"feed": "FUNCTIONS/SPORTS", "fallback_feed": None, "max_stale": 3600},
}


class CategoricalMappingTests(unittest.TestCase):
    def setUp(self):
        self.reg = FeedRegistry()

    def test_builds_valid_categorical_args(self):
        args = build_categorical_create_market_args(CATEGORICAL_PROPOSAL, 10200, self.reg, NOW)
        self.assertEqual(args.outcome_count, 3)  # from the outcomes list
        self.assertEqual(len(args.oracle_params) - 2, 192)  # 96 bytes
        self.assertEqual(len(args.as_tx_args()), 4)
        self.assertEqual(args.as_tx_args()[2], 3)  # outcomeCount in positional args
        self.assertTrue(args.market_id.startswith("0x"))

    def test_outcome_count_field_used_when_no_list(self):
        p = {k: v for k, v in CATEGORICAL_PROPOSAL.items() if k != "outcomes"}
        p["outcome_count"] = 5
        args = build_categorical_create_market_args(p, 10200, self.reg, NOW)
        self.assertEqual(args.outcome_count, 5)

    def test_market_id_matches_binary_derivation(self):
        # same keccak(questionHash, closeAt, chainId) -> dedupe is cross-consistent
        from oracleforge_relayer import abi
        args = build_categorical_create_market_args(CATEGORICAL_PROPOSAL, 10200, self.reg, NOW)
        qh = abi.question_hash(CATEGORICAL_PROPOSAL["question"])
        self.assertEqual(args.market_id, abi.market_id(qh, CATEGORICAL_PROPOSAL["close_at"], 10200))

    def test_too_few_outcomes_skips(self):
        p = {**CATEGORICAL_PROPOSAL, "outcomes": ["only-one"]}
        with self.assertRaises(SkipProposal):
            build_categorical_create_market_args(p, 10200, self.reg, NOW)

    def test_too_many_outcomes_skips(self):
        p = {k: v for k, v in CATEGORICAL_PROPOSAL.items() if k != "outcomes"}
        p["outcome_count"] = 65  # engine caps at 64
        with self.assertRaises(SkipProposal):
            build_categorical_create_market_args(p, 10200, self.reg, NOW)

    def test_missing_outcomes_skips(self):
        p = {k: v for k, v in CATEGORICAL_PROPOSAL.items() if k != "outcomes"}
        with self.assertRaises(SkipProposal):
            build_categorical_create_market_args(p, 10200, self.reg, NOW)

    def test_unknown_feed_skips(self):
        p = {**CATEGORICAL_PROPOSAL, "oracle": {**CATEGORICAL_PROPOSAL["oracle"], "feed": "MYSTERY"}}
        with self.assertRaises(SkipProposal):
            build_categorical_create_market_args(p, 10200, self.reg, NOW)


class CategoricalOrchestrationTests(unittest.TestCase):
    def _relayer(self):
        chain = DryRunChain(chain_id=10200)
        return Relayer(chain, FeedRegistry(), now_ts_fn=lambda: NOW), chain

    def test_run_categorical_submits(self):
        relayer, chain = self._relayer()
        [r] = relayer.run_categorical([CATEGORICAL_PROPOSAL])
        self.assertEqual(r.status, "submitted")
        self.assertEqual(len(chain.categorical_submitted), 1)
        self.assertEqual(chain.categorical_submitted[0].outcome_count, 3)
        self.assertTrue(r.tx_hash.startswith("0xDRYCAT"))

    def test_categorical_idempotent_second_run_sees_exists(self):
        relayer, _ = self._relayer()
        relayer.run_categorical([CATEGORICAL_PROPOSAL])
        [r] = relayer.run_categorical([CATEGORICAL_PROPOSAL])
        self.assertEqual(r.status, "exists")

    def test_categorical_bad_proposal_skips_not_errors(self):
        relayer, _ = self._relayer()
        bad = {**CATEGORICAL_PROPOSAL, "outcomes": ["only-one"]}
        [r] = relayer.run_categorical([bad])
        self.assertEqual(r.status, "skipped")


class ScalarOrchestrationTests(unittest.TestCase):
    def _relayer(self):
        chain = DryRunChain(chain_id=10200)
        return Relayer(chain, FeedRegistry(), now_ts_fn=lambda: NOW), chain

    def test_run_scalar_submits(self):
        relayer, chain = self._relayer()
        [r] = relayer.run_scalar([SCALAR_PROPOSAL])
        self.assertEqual(r.status, "submitted")
        self.assertEqual(len(chain.scalar_submitted), 1)
        self.assertEqual(chain.scalar_submitted[0].upper, 5000)
        self.assertTrue(r.tx_hash.startswith("0xDRYSCL"))

    def test_scalar_idempotent_second_run_sees_exists(self):
        relayer, _ = self._relayer()
        relayer.run_scalar([SCALAR_PROPOSAL])
        [r] = relayer.run_scalar([SCALAR_PROPOSAL])
        self.assertEqual(r.status, "exists")

    def test_scalar_bad_proposal_skips_not_errors(self):
        relayer, _ = self._relayer()
        bad = {**SCALAR_PROPOSAL, "band": {"lower": 5000, "upper": 3000}}
        [r] = relayer.run_scalar([bad])
        self.assertEqual(r.status, "skipped")


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
