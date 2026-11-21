"""Anvil devnet parity test — SCALAR (range) engine.

Boots a real anvil node, deploys the actual ``ScalarMarketEngine`` +
``MockScalarOracle``, runs the full lifecycle, and asserts the on-chain payouts
and fee equal the Python ``scalar_settle()`` port across three scenarios (value
inside the band, clamped above it, and a one-sided void). Skips cleanly when the
Foundry toolchain is not on PATH, like the binary devnet test beside it.
"""
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

_HAVE_FOUNDRY = all(shutil.which(b) for b in ("anvil", "forge", "cast"))


@unittest.skipUnless(_HAVE_FOUNDRY, "anvil/forge/cast not on PATH")
class TestScalarDevnetParity(unittest.TestCase):
    def _check(self, scenario: str):
        from devnet import Devnet
        from scalar_devnet import run_scalar_devnet

        dev = Devnet.start()
        try:
            res = run_scalar_devnet(scenario)
        finally:
            dev.stop()
        # the real ScalarMarketEngine must pay exactly what the Python port computes
        self.assertEqual(res["onchain_payouts"], res["expected_payouts"])
        self.assertEqual(res["onchain_fee"], res["expected_fee"])
        self.assertEqual(res["voided"], res["expected_void"])
        self.assertTrue(res["parity"])
        self.assertTrue(res["market_id"].startswith("0x"))
        return res

    def test_mid_band_both_sides_paid(self):
        res = self._check("mid")
        self.assertFalse(res["voided"])
        self.assertGreater(res["onchain_fee"], 0)
        # both LONG and SHORT accounts receive a positive payout
        self.assertTrue(all(p > 0 for p in res["onchain_payouts"].values()))

    def test_clamp_above_band_long_takes_all(self):
        res = self._check("clamp")
        self.assertFalse(res["voided"])
        # value clamps to the upper bound: SHORT accounts are paid 0 (and did not
        # revert on claim — the key difference from the binary loser path)
        self.assertEqual(res["onchain_payouts"]["0xCarol"], 0)
        self.assertEqual(res["onchain_payouts"]["0xDave"], 0)
        self.assertGreater(res["onchain_payouts"]["0xAlice"], 0)

    def test_one_sided_book_voids_and_refunds(self):
        res = self._check("void")
        self.assertTrue(res["voided"])
        self.assertEqual(res["onchain_fee"], 0)
        # principals refunded exactly
        self.assertEqual(res["onchain_payouts"], {"0xAlice": 600, "0xBob": 400})


if __name__ == "__main__":
    unittest.main()
