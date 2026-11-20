"""Scalar planner tests — the pure decision logic for range markets."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from oracleforge_resolver.models import Action, Market, Status  # noqa: E402
from oracleforge_resolver.planner import plan_scalar_one  # noqa: E402

NOW = 1_800_000_000
DAY = 86400


def _val(ready, value):
    return lambda _mid: (ready, value)


class ScalarPlannerTests(unittest.TestCase):
    def _m(self, close_delta, status=Status.Open):
        return Market("0xabc", NOW + close_delta, status)

    def test_not_closed_waits(self):
        d = plan_scalar_one(self._m(+DAY), NOW, _val(True, 150))
        self.assertEqual(d.action, Action.WAIT)

    def test_already_settled_skips_without_oracle_call(self):
        called = []
        plan_scalar_one(self._m(-DAY, Status.Resolved), NOW,
                        lambda m: called.append(m) or (True, 150))
        self.assertEqual(called, [])  # oracle not consulted for settled markets

    def test_closed_feed_not_ready_pending(self):
        d = plan_scalar_one(self._m(-DAY), NOW, _val(False, 0))
        self.assertEqual(d.action, Action.PENDING)

    def test_closed_ready_resolves_with_value(self):
        d = plan_scalar_one(self._m(-DAY), NOW, _val(True, 4200))
        self.assertEqual(d.action, Action.RESOLVE)
        self.assertEqual(d.predicted_value, 4200)
        self.assertIsNone(d.predicted_outcome)  # scalar carries value, not outcome

    def test_negative_value_is_passed_through(self):
        # the engine clamps; the planner just proposes whatever the adapter reports
        d = plan_scalar_one(self._m(-DAY), NOW, _val(True, -5))
        self.assertEqual(d.action, Action.RESOLVE)
        self.assertEqual(d.predicted_value, -5)


class ScalarDisputeWindowTests(unittest.TestCase):
    def _proposed(self, proposed_delta):
        return Market("0xabc", NOW - DAY, Status.Closed, proposed_at=NOW + proposed_delta)

    def test_within_window_waits(self):
        d = plan_scalar_one(self._proposed(-100), NOW, _val(True, 150), challenge_window=3600)
        self.assertEqual(d.action, Action.WAIT)
        self.assertIn("challenge window", d.reason)

    def test_after_window_finalizes_with_value(self):
        d = plan_scalar_one(self._proposed(-7200), NOW, _val(True, 150), challenge_window=3600)
        self.assertEqual(d.action, Action.FINALIZE)
        self.assertEqual(d.predicted_value, 150)

    def test_zero_window_finalizes_immediately(self):
        d = plan_scalar_one(self._proposed(0), NOW, _val(True, 150))  # default window 0
        self.assertEqual(d.action, Action.FINALIZE)
        self.assertEqual(d.predicted_value, 150)

    def test_open_past_close_still_proposes_under_window(self):
        d = plan_scalar_one(
            Market("0xabc", NOW - DAY, Status.Open), NOW, _val(True, 150), challenge_window=3600
        )
        self.assertEqual(d.action, Action.RESOLVE)


if __name__ == "__main__":
    unittest.main()
