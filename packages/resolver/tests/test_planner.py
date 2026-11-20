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


class DisputeWindowTests(unittest.TestCase):
    """The Status.Closed branch: a proposed outcome waits out its window, then
    finalizes. (RESOLVE = 'propose'; FINALIZE = 'lock it in'.)"""

    def _proposed(self, proposed_delta):
        return Market("0xabc", NOW - DAY, Status.Closed, proposed_at=NOW + proposed_delta)

    def test_within_window_waits(self):
        d = plan_one(self._proposed(-100), NOW, _const(Outcome.Yes), challenge_window=3600)
        self.assertEqual(d.action, Action.WAIT)
        self.assertIn("challenge window", d.reason)

    def test_after_window_finalizes_with_outcome(self):
        d = plan_one(self._proposed(-7200), NOW, _const(Outcome.Yes), challenge_window=3600)
        self.assertEqual(d.action, Action.FINALIZE)
        self.assertEqual(d.predicted_outcome, 1)

    def test_zero_window_finalizes_immediately(self):
        d = plan_one(self._proposed(0), NOW, _const(Outcome.No))  # default window 0
        self.assertEqual(d.action, Action.FINALIZE)
        self.assertEqual(d.predicted_outcome, 0)

    def test_open_market_still_proposes_under_a_window(self):
        # the window governs only the Closed->finalize step; an Open past-close
        # market is still RESOLVE (propose).
        d = plan_one(
            Market("0xabc", NOW - DAY, Status.Open), NOW, _const(Outcome.Yes),
            challenge_window=3600,
        )
        self.assertEqual(d.action, Action.RESOLVE)


if __name__ == "__main__":
    unittest.main()
