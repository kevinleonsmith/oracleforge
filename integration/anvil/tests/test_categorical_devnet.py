"""Anvil devnet parity test — CATEGORICAL (N-outcome) engine.

Boots a real anvil node, deploys the actual ``CategoricalMarketEngine`` +
``MockCategoricalOracle``, runs the full lifecycle, and asserts the on-chain
payouts and fee equal the Python ``categorical_settle()`` port across three
scenarios (a funded winner, a winning outcome with no stake, and the invalid
sentinel). Skips cleanly when the Foundry toolchain is not on PATH, like the
binary/scalar devnet tests beside it.
"""
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

_HAVE_FOUNDRY = all(shutil.which(b) for b in ("anvil", "forge", "cast"))


@unittest.skipUnless(_HAVE_FOUNDRY, "anvil/forge/cast not on PATH")
class TestCategoricalDevnetParity(unittest.TestCase):
    def _check(self, scenario: str):
        from categorical_devnet import run_categorical_devnet
        from devnet import Devnet

        dev = Devnet.start()
        try:
            res = run_categorical_devnet(scenario)
        finally:
            dev.stop()
        # the real CategoricalMarketEngine must pay exactly what the port computes
        self.assertEqual(res["onchain_payouts"], res["expected_payouts"])
        self.assertEqual(res["onchain_fee"], res["expected_fee"])
        self.assertEqual(res["voided"], res["expected_void"])
        self.assertTrue(res["parity"])
        self.assertTrue(res["market_id"].startswith("0x"))
        return res

    def test_funded_winner_pays_pro_rata(self):
        res = self._check("winner")
        self.assertFalse(res["voided"])
        self.assertGreater(res["onchain_fee"], 0)
        # only the winning-outcome accounts are paid (losers' claims revert)
        self.assertEqual(set(res["onchain_payouts"]), {"0xAlice", "0xBob"})
        self.assertTrue(all(p > 0 for p in res["onchain_payouts"].values()))

    def test_empty_winning_outcome_voids(self):
        res = self._check("void_empty")
        self.assertTrue(res["voided"])
        self.assertEqual(res["onchain_fee"], 0)
        # every principal refunded
        self.assertEqual(
            res["onchain_payouts"],
            {"0xAlice": 600, "0xBob": 400, "0xCarol": 500, "0xDave": 500},
        )

    def test_invalid_sentinel_voids(self):
        res = self._check("void_invalid")
        self.assertTrue(res["voided"])
        self.assertEqual(res["onchain_fee"], 0)
        self.assertEqual(
            res["onchain_payouts"],
            {"0xAlice": 600, "0xBob": 400, "0xCarol": 500, "0xDave": 500},
        )


if __name__ == "__main__":
    unittest.main()
