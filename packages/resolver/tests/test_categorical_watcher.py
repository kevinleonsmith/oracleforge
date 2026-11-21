"""Categorical watcher orchestration tests (no chain/network)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from oracleforge_resolver.archive import LogReportSink  # noqa: E402
from oracleforge_resolver.chain import DryRunResolver  # noqa: E402
from oracleforge_resolver.models import Market, Status  # noqa: E402
from oracleforge_resolver.oracle import StubCategoricalOracleView  # noqa: E402
from oracleforge_resolver.planner import INVALID_OUTCOME  # noqa: E402
from oracleforge_resolver.sources import StaticMarketSource  # noqa: E402
from oracleforge_resolver.watcher import CategoricalWatcher  # noqa: E402

NOW = 1_800_000_000
DAY = 86400

M_WIN = "0x" + "a1" * 32
M_VOID = "0x" + "b2" * 32
M_WAIT = "0x" + "c3" * 32
M_PENDING = "0x" + "d4" * 32
M_SETTLED = "0x" + "e5" * 32


def _markets():
    return [
        Market(M_WIN, NOW - DAY, Status.Open, feed="SPORTS/CHAMPION"),
        Market(M_VOID, NOW - DAY, Status.Open, feed="ELECTION/SEAT"),
        Market(M_WAIT, NOW + 5 * DAY, Status.Open),
        Market(M_PENDING, NOW - DAY, Status.Open),
        Market(M_SETTLED, NOW - 2 * DAY, Status.Resolved),
    ]


def _watcher(markets, window=0):
    outcomes = {
        M_WIN: (True, 2),
        M_VOID: (True, INVALID_OUTCOME),
        M_PENDING: (False, 0),
    }
    sink = LogReportSink()
    w = CategoricalWatcher(DryRunResolver(), StubCategoricalOracleView(outcomes),
                           StaticMarketSource(markets), sink, now_fn=lambda: NOW,
                           challenge_window=window)
    return w, sink


class CategoricalTickTests(unittest.TestCase):
    def test_tick_classifies_each_market(self):
        w, _ = _watcher(_markets())
        res = {r.market_id: r for r in w.tick()}
        self.assertEqual(res[M_WIN].status, "resolved")
        self.assertEqual(res[M_VOID].status, "resolved")  # void still resolves on-chain
        self.assertEqual(res[M_WAIT].status, "waiting")
        self.assertEqual(res[M_PENDING].status, "pending")
        self.assertEqual(res[M_SETTLED].status, "settled")

    def test_resolved_market_archives_winning_index(self):
        w, sink = _watcher(_markets())
        w.tick()
        self.assertIn(M_WIN, w.resolver.resolved)
        report = next(r for r in sink.reports if r.market_id == M_WIN)
        self.assertEqual(report.kind, "categorical")
        self.assertEqual(report.outcome, 2)  # the winning index
        self.assertEqual(report.feed, "SPORTS/CHAMPION")

    def test_void_market_archives_minus_one(self):
        w, sink = _watcher(_markets())
        w.tick()
        report = next(r for r in sink.reports if r.market_id == M_VOID)
        self.assertEqual(report.kind, "categorical")
        self.assertEqual(report.outcome, -1)  # void


class CategoricalDisputeWindowTests(unittest.TestCase):
    WINDOW = 3600

    def test_open_market_is_proposed_not_archived(self):
        markets = [Market(M_WIN, NOW - DAY, Status.Open, feed="SPORTS/CHAMPION")]
        w, sink = _watcher(markets, window=self.WINDOW)
        [r] = w.tick()
        self.assertEqual(r.status, "proposed")
        self.assertEqual(w.resolver.resolved, [M_WIN])  # propose tx sent
        self.assertEqual(w.resolver.finalized, [])
        self.assertEqual(sink.reports, [])  # NOT archived until finalized

    def test_closed_inside_window_waits(self):
        markets = [Market(M_WIN, NOW - DAY, Status.Closed, proposed_at=NOW - 100, feed="SPORTS/CHAMPION")]
        w, _ = _watcher(markets, window=self.WINDOW)
        [r] = w.tick()
        self.assertEqual(r.status, "waiting")
        self.assertEqual(w.resolver.finalized, [])

    def test_closed_after_window_finalizes_and_archives_index(self):
        markets = [Market(M_WIN, NOW - DAY, Status.Closed,
                          proposed_at=NOW - 2 * self.WINDOW, feed="SPORTS/CHAMPION")]
        w, sink = _watcher(markets, window=self.WINDOW)
        [r] = w.tick()
        self.assertEqual(r.status, "finalized")
        self.assertEqual(w.resolver.finalized, [M_WIN])
        self.assertEqual(sink.reports[0].outcome, 2)
        self.assertEqual(sink.reports[0].kind, "categorical")

    def test_finalize_revert_is_reported_not_crash(self):
        class Reverting(DryRunResolver):
            def finalize(self, market_id):
                raise RuntimeError("CAT: disputed")

        markets = [Market(M_WIN, NOW - DAY, Status.Closed, proposed_at=NOW - 2 * self.WINDOW)]
        sink = LogReportSink()
        w = CategoricalWatcher(Reverting(), StubCategoricalOracleView({M_WIN: (True, 2)}),
                               StaticMarketSource(markets), sink, now_fn=lambda: NOW,
                               challenge_window=self.WINDOW)
        [r] = w.tick()
        self.assertEqual(r.status, "error")
        self.assertIn("disputed", r.detail)


if __name__ == "__main__":
    unittest.main()
