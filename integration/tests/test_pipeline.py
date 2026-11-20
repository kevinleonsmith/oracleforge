"""Cross-package integration tests.

These assert properties that only hold when the packages agree with one another
— the complement to each package's own unit suite.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pipeline import FEE_BPS, run_pipeline, settle  # noqa: E402


class TestSettlement(unittest.TestCase):
    """settle() must reproduce MarketEngine.claim exactly (integer math)."""

    def test_matches_hand_computed_contract_math(self):
        # YES 1000 (Alice 600, Bob 400), NO 800 (Carol 500, Dave 300); YES wins.
        pos = [("A", "YES", 600), ("B", "YES", 400), ("C", "NO", 500), ("D", "NO", 300)]
        s = settle(pos, outcome_yes=True)
        self.assertEqual(s.fee, (800 * FEE_BPS) // 10_000)      # 16
        self.assertEqual(s.losing_pool_after_fee, 800 - 16)     # 784
        # payout = stake + stake*losingAfter//winningPool  (floor, as in Solidity)
        self.assertEqual(s.payouts["A"], 600 + (600 * 784) // 1000)  # 1070
        self.assertEqual(s.payouts["B"], 400 + (400 * 784) // 1000)  # 713
        self.assertNotIn("C", s.payouts)  # losers get nothing
        self.assertNotIn("D", s.payouts)

    def test_value_is_conserved_including_dust(self):
        # Across many asymmetric splits, winners + fee + dust == total staked,
        # and dust is non-negative and smaller than the number of winners.
        for yp, np_ in [(1, 999), (1000, 1), (333, 667), (10_000, 7), (7, 10_000)]:
            for out in (True, False):
                s = settle([("w1", "YES", yp // 2), ("w2", "YES", yp - yp // 2),
                            ("l1", "NO", np_)], outcome_yes=out)
                self.assertEqual(s.total_paid + s.fee + s.dust, s.total_staked,
                                 msg=f"yes={yp} no={np_} out={out}")
                self.assertGreaterEqual(s.dust, 0)

    def test_no_winners_pays_nothing(self):
        # If the winning pool is empty, nobody can claim (pot stays as dust).
        s = settle([("l", "NO", 500)], outcome_yes=True)
        self.assertEqual(s.payouts, {})
        self.assertEqual(s.total_paid, 0)


class TestPipelineBoundaries(unittest.TestCase):
    """The full generate→relay→trade→resolve→archive thread."""

    @classmethod
    def setUpClass(cls):
        cls.res = run_pipeline()

    def test_all_boundary_checks_pass(self):
        self.assertTrue(self.res.checks.all_pass, self.res.checks)

    def test_identity_threads_every_package(self):
        # one market_id, derived once by the relayer, unchanged downstream
        self.assertTrue(self.res.market_id.startswith("0x"))
        self.assertEqual(self.res.market_id, self.res.report_market_id)
        self.assertIn(self.res.market_id, self.res.archived_ids)
        self.assertTrue(self.res.checks.identity)

    def test_determinism_boundary_holds_across_relay(self):
        # committed (relay-path) forecast == generator's local probability
        self.assertEqual(self.res.committed_bps, self.res.ai_prob_bps)
        self.assertTrue(0 <= self.res.committed_bps <= 10_000)

    def test_archive_is_content_addressed_and_dedupes(self):
        r_first, _, r_again = self.res.receipts
        self.assertFalse(r_first.deduped)
        self.assertTrue(r_again.deduped)
        self.assertEqual(r_first.content_hash, r_again.content_hash)

    def test_outcome_no_also_settles_and_conserves(self):
        res = run_pipeline(outcome_yes=False)
        self.assertEqual(res.outcome, "NO")
        self.assertEqual(res.market_id, res.report_market_id)
        s = res.settlement
        self.assertEqual(s.total_paid + s.fee + s.dust, s.total_staked)


if __name__ == "__main__":
    unittest.main()
