"""Pure planning tests for categorical (N-outcome) markets."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from oracleforge_resolver.models import Action, Market, Status  # noqa: E402
from oracleforge_resolver.planner import (  # noqa: E402
    INVALID_OUTCOME,
    plan_categorical,
    plan_categorical_one,
)

NOW = 1_800_000_000
DAY = 86400
MID = "0x" + "a1" * 32


def _market(status=Status.Open, close_at=NOW - DAY, proposed_at=0):
    return Market(MID, close_at, status, feed="SPORTS/CHAMPION", proposed_at=proposed_at)


class CategoricalPlannerTests(unittest.TestCase):
    def test_waits_before_close(self):
        d = plan_categorical_one(_market(close_at=NOW + DAY), NOW, lambda _: (True, 1))
        self.assertEqual(d.action, Action.WAIT)

    def test_pending_when_oracle_not_ready(self):
        d = plan_categorical_one(_market(), NOW, lambda _: (False, 0))
        self.assertEqual(d.action, Action.PENDING)

    def test_resolves_to_winning_index(self):
        d = plan_categorical_one(_market(), NOW, lambda _: (True, 2))
        self.assertEqual(d.action, Action.RESOLVE)
        self.assertEqual(d.predicted_outcome, 2)
        self.assertIn("outcome 2", d.reason)

    def test_resolves_to_void_on_invalid_sentinel(self):
        d = plan_categorical_one(_market(), NOW, lambda _: (True, INVALID_OUTCOME))
        self.assertEqual(d.action, Action.RESOLVE)
        self.assertIsNone(d.predicted_outcome)  # None == void
        self.assertIn("INVALID", d.reason)

    def test_sentinel_threshold_is_exact(self):
        # 0xFF (the uint8 oracle's invalid sentinel) is void; anything below it is
        # taken as a real winning index (the resolver trusts the oracle's range —
        # the engine independently voids a genuinely out-of-range index).
        void = plan_categorical_one(_market(), NOW, lambda _: (True, INVALID_OUTCOME))
        self.assertIsNone(void.predicted_outcome)
        idx = plan_categorical_one(_market(), NOW, lambda _: (True, INVALID_OUTCOME - 1))
        self.assertEqual(idx.predicted_outcome, INVALID_OUTCOME - 1)

    def test_settled_markets_are_left_alone(self):
        for st in (Status.Resolved, Status.Invalid):
            d = plan_categorical_one(_market(status=st), NOW, lambda _: (True, 1))
            self.assertEqual(d.action, Action.SETTLED)

    def test_closed_inside_window_waits(self):
        d = plan_categorical_one(
            _market(status=Status.Closed, proposed_at=NOW - 100), NOW,
            lambda _: (True, 1), challenge_window=3600,
        )
        self.assertEqual(d.action, Action.WAIT)
        self.assertIn("challenge window", d.reason)

    def test_closed_after_window_finalizes_with_index(self):
        d = plan_categorical_one(
            _market(status=Status.Closed, proposed_at=NOW - 7200), NOW,
            lambda _: (True, 1), challenge_window=3600,
        )
        self.assertEqual(d.action, Action.FINALIZE)
        self.assertEqual(d.predicted_outcome, 1)

    def test_closed_after_window_finalizes_void(self):
        d = plan_categorical_one(
            _market(status=Status.Closed, proposed_at=NOW - 7200), NOW,
            lambda _: (True, INVALID_OUTCOME), challenge_window=3600,
        )
        self.assertEqual(d.action, Action.FINALIZE)
        self.assertIsNone(d.predicted_outcome)

    def test_plan_maps_over_a_batch(self):
        markets = [_market(), _market(close_at=NOW + DAY)]
        ds = plan_categorical(markets, NOW, lambda _: (True, 0))
        self.assertEqual([d.action for d in ds], [Action.RESOLVE, Action.WAIT])


if __name__ == "__main__":
    unittest.main()
