"""Anvil devnet parity test.

Boots a real anvil node, deploys the actual contracts, runs the full lifecycle,
and asserts the on-chain payouts/fee equal the Python ``settle()`` port. Skips
cleanly when the Foundry toolchain is not on PATH, so it never breaks a run that
lacks anvil/forge/cast (the pure suite in ``integration/tests`` always runs).
"""
import os
import shutil
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

_HAVE_FOUNDRY = all(shutil.which(b) for b in ("anvil", "forge", "cast"))


@unittest.skipUnless(_HAVE_FOUNDRY, "anvil/forge/cast not on PATH")
class TestDevnetParity(unittest.TestCase):
    def _check(self, outcome_yes: bool):
        from devnet import Devnet, run_devnet

        dev = Devnet.start()
        try:
            res = run_devnet(outcome_yes=outcome_yes)
        finally:
            dev.stop()
        # the real MarketEngine must pay exactly what the Python port computes
        self.assertEqual(res["onchain_payouts"], res["expected_payouts"])
        self.assertEqual(res["onchain_fee"], res["expected_fee"])
        self.assertTrue(res["parity"])
        self.assertTrue(res["market_id"].startswith("0x"))
        return res

    def test_yes_outcome_parity(self):
        res = self._check(outcome_yes=True)
        # YES wins: Alice + Bob are paid, losers excluded
        self.assertEqual(set(res["onchain_payouts"]), {"0xAlice", "0xBob"})

    def test_no_outcome_parity(self):
        res = self._check(outcome_yes=False)
        # NO wins: Carol + Dave are paid
        self.assertEqual(set(res["onchain_payouts"]), {"0xCarol", "0xDave"})


if __name__ == "__main__":
    unittest.main()
