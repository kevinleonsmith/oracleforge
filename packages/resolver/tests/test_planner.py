"""Planner tests — the pure decision logic."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from oracleforge_resolver.models import Action, Market, Outcome, Status, status_from  # noqa: E402
from oracleforge_resolver.planner import plan_one  # noqa: E402

NOW = 1_800_000_000
DAY = 86400


def _const(outcome):
    return lambda _mid: outcome


class StatusNormalizeTests(unittest.TestCase):
    def test_from_text_and_int(self):
        self.assertEqual(status_from("OPEN"), Status.Open)
        self.assertEqual(status_from("resolved"), Status.Resolved)
        self.assertEqual(status_from(3), Status.Invalid)


class PlannerTests(unittest.TestCase):
    def _m(self, close_delta, status=Status.Open):
        return Market("0xabc", NOW + close_delta, status)

    def test_not_closed_waits(self):
        d = plan_one(self._m(+DAY), NOW, _const(Outcome.Yes))
        self.assertEqual(d.action, Action.WAIT)

    def test_already_settled_skips_without_oracle_call(self):
        called = []
        plan_one(self._m(-DAY, Status.Resolved), NOW, lambda m: called.append(m) or Outcome.Yes)
        self.assertEqual(called, [])  # oracle not consulted for settled markets

    def test_closed_pending_oracle(self):
        d = plan_one(self._m(-DAY), NOW, _const(Outcome.Pending))
        self.assertEqual(d.action, Action.PENDING)

    def test_closed_ready_yes(self):
        d = plan_one(self._m(-DAY), NOW, _const(Outcome.Yes))
        self.assertEqual(d.action, Action.RESOLVE)
        self.assertEqual(d.predicted_outcome, 1)

    def test_closed_ready_no(self):
        d = plan_one(self._m(-DAY), NOW, _const(Outcome.No))
        self.assertEqual(d.action, Action.RESOLVE)
        self.assertEqual(d.predicted_outcome, 0)

    def test_closed_invalid_voids(self):
        d = plan_one(self._m(-DAY), NOW, _const(Outcome.Invalid))
        self.assertEqual(d.action, Action.RESOLVE)
        self.assertIsNone(d.predicted_outcome)  # None => void


if __name__ == "__main__":
    unittest.main()
