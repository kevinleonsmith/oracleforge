"""Cross-package integration tests.

These assert properties that only hold when the packages agree with one another
— the complement to each package's own unit suite.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pipeline import (  # noqa: E402
    CATEGORICAL_DEMO_OUTCOMES,
    CATEGORICAL_DEMO_POSITIONS,
    FEE_BPS,
    SCALAR_DEMO_BAND,
    SCALAR_DEMO_POSITIONS,
    categorical_settle,
    run_pipeline,
    scalar_settle,
    settle,
)


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


class TestScalarSettlement(unittest.TestCase):
    """scalar_settle() must reproduce ScalarMarketEngine._payoutPools + claim."""

    def test_matches_hand_computed_contract_math(self):
        lower, upper = SCALAR_DEMO_BAND  # [100, 200]
        s = scalar_settle(SCALAR_DEMO_POSITIONS, 150, lower, upper)
        # pot 1800, fee 2% = 36, distributable 1764, f = 50/100 = 0.5
        self.assertEqual(s.fee, (1800 * FEE_BPS) // 10_000)   # 36
        self.assertEqual(s.long_payout, (1764 * 50) // 100)   # 882
        self.assertEqual(s.short_payout, 1764 - 882)          # 882
        # each account's pro-rata share of its side (floor division, as Solidity)
        self.assertEqual(s.payouts["0xAlice"], (882 * 600) // 1000)  # 529
        self.assertEqual(s.payouts["0xBob"], (882 * 400) // 1000)    # 352
        self.assertEqual(s.payouts["0xCarol"], (882 * 500) // 800)   # 551
        self.assertEqual(s.payouts["0xDave"], (882 * 300) // 800)    # 330
        self.assertFalse(s.void)

    def test_clamp_above_band_pays_long_only(self):
        lower, upper = SCALAR_DEMO_BAND
        s = scalar_settle(SCALAR_DEMO_POSITIONS, 999, lower, upper)
        self.assertEqual(s.settled_value, upper)   # clamped to 200
        self.assertEqual(s.short_payout, 0)
        self.assertEqual(s.payouts["0xCarol"], 0)
        self.assertEqual(s.payouts["0xDave"], 0)
        self.assertGreater(s.payouts["0xAlice"], 0)

    def test_clamp_below_band_pays_short_only(self):
        lower, upper = SCALAR_DEMO_BAND
        s = scalar_settle(SCALAR_DEMO_POSITIONS, 1, lower, upper)
        self.assertEqual(s.settled_value, lower)   # clamped to 100
        self.assertEqual(s.long_payout, 0)
        self.assertEqual(s.payouts["0xAlice"], 0)
        self.assertGreater(s.payouts["0xCarol"], 0)

    def test_one_sided_book_voids_and_refunds_principal(self):
        s = scalar_settle([("a", "LONG", 600), ("b", "LONG", 400)], 150, 100, 200)
        self.assertTrue(s.void)
        self.assertEqual(s.fee, 0)
        self.assertEqual(s.payouts, {"a": 600, "b": 400})

    def test_value_is_conserved_including_dust(self):
        # For any book and any settlement value: paid + fee + dust == staked,
        # dust non-negative (floor-division remainder retained in the contract).
        for lp, sp in [(1, 999), (1000, 1), (333, 667), (10_000, 7), (7, 10_000)]:
            for v in (100, 125, 150, 175, 200):
                s = scalar_settle([("l1", "LONG", lp // 2), ("l2", "LONG", lp - lp // 2),
                                   ("s1", "SHORT", sp)], v, 100, 200)
                self.assertEqual(s.total_paid + s.fee + s.dust, s.total_staked,
                                 msg=f"long={lp} short={sp} v={v}")
                self.assertGreaterEqual(s.dust, 0)

    def test_long_payout_is_monotone_in_value(self):
        # A higher settlement value never pays the LONG side less (the contract's
        # monotonicity property, mirrored by the port).
        lower, upper = SCALAR_DEMO_BAND
        last = -1
        for v in range(lower, upper + 1, 5):
            s = scalar_settle(SCALAR_DEMO_POSITIONS, v, lower, upper)
            self.assertGreaterEqual(s.long_payout, last)
            last = s.long_payout


class TestCategoricalSettlement(unittest.TestCase):
    """categorical_settle() must reproduce CategoricalMarketEngine resolve + claim."""

    def test_matches_hand_computed_contract_math(self):
        # outcome 0 = Alice 600 + Bob 400 (1000); outcome 1 = Carol 500;
        # outcome 2 = Dave 500. Winner 0. pot 2000, losing 1000, fee 20, net 980.
        s = categorical_settle(CATEGORICAL_DEMO_POSITIONS, 0, CATEGORICAL_DEMO_OUTCOMES)
        self.assertEqual(s.winning_pool, 1000)
        self.assertEqual(s.fee, (1000 * FEE_BPS) // 10_000)   # 20
        self.assertEqual(s.losing_pool_net, 980)
        self.assertEqual(s.payouts["0xAlice"], 600 + (600 * 980) // 1000)  # 1188
        self.assertEqual(s.payouts["0xBob"], 400 + (400 * 980) // 1000)    # 792
        self.assertNotIn("0xCarol", s.payouts)  # losers get nothing
        self.assertNotIn("0xDave", s.payouts)
        self.assertFalse(s.void)

    def test_empty_winning_outcome_voids_and_refunds(self):
        # a 3-outcome book with stake only on 0 and 1; outcome 2 wins -> void
        book = [("a", 0, 100), ("b", 1, 200)]
        funded = categorical_settle(book, 1, 3)
        self.assertFalse(funded.void)  # outcome 1 has stake -> settles
        empty = categorical_settle(book, 2, 3)
        self.assertTrue(empty.void)    # outcome 2 empty -> void
        self.assertEqual(empty.fee, 0)
        self.assertEqual(empty.payouts, {"a": 100, "b": 200})

    def test_invalid_sentinel_voids(self):
        s = categorical_settle(CATEGORICAL_DEMO_POSITIONS, 0xFF, CATEGORICAL_DEMO_OUTCOMES)
        self.assertTrue(s.void)
        self.assertEqual(s.fee, 0)
        self.assertEqual(sum(s.payouts.values()), 2000)  # all principal refunded

    def test_value_is_conserved_including_dust(self):
        # For any book and winner: paid + fee + dust == staked, dust non-negative.
        for w0, w1, l in [(1, 999, 500), (1000, 1, 7), (333, 667, 10_000)]:
            s = categorical_settle(
                [("w1", 0, w0), ("w2", 0, w1), ("l1", 1, l)], 0, 2)
            self.assertEqual(s.total_paid + s.fee + s.dust, s.total_staked,
                             msg=f"w0={w0} w1={w1} l={l}")
            self.assertGreaterEqual(s.dust, 0)
            self.assertEqual(s.fee, (l * FEE_BPS) // 10_000)


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
