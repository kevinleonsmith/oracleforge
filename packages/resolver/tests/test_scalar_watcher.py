"""Scalar watcher orchestration tests (no chain/network)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from oracleforge_resolver.archive import LogReportSink  # noqa: E402
from oracleforge_resolver.chain import DryRunResolver  # noqa: E402
from oracleforge_resolver.models import Market, Status  # noqa: E402
from oracleforge_resolver.oracle import StubScalarOracleView  # noqa: E402
from oracleforge_resolver.sources import StaticMarketSource  # noqa: E402
from oracleforge_resolver.watcher import ScalarWatcher  # noqa: E402

NOW = 1_800_000_000
DAY = 86400

M_READY = "0x" + "a1" * 32
M_WAIT = "0x" + "c3" * 32
M_PENDING = "0x" + "d4" * 32
M_SETTLED = "0x" + "e5" * 32


def _markets():
    return [
        Market(M_READY, NOW - DAY, Status.Open, feed="ETH/USD"),
        Market(M_WAIT, NOW + 5 * DAY, Status.Open),
        Market(M_PENDING, NOW - DAY, Status.Open),
        Market(M_SETTLED, NOW - 2 * DAY, Status.Resolved),
    ]


def _watcher(markets, window=0):
    values = {M_READY: (True, 4200), M_PENDING: (False, 0)}
    sink = LogReportSink()
    w = ScalarWatcher(DryRunResolver(), StubScalarOracleView(values),
                      StaticMarketSource(markets), sink, now_fn=lambda: NOW,
                      challenge_window=window)
    return w, sink


class ScalarTickTests(unittest.TestCase):
    def test_tick_classifies_each_market(self):
        w, _ = _watcher(_markets())
        res = {r.market_id: r for r in w.tick()}
        self.assertEqual(res[M_READY].status, "resolved")
        self.assertEqual(res[M_WAIT].status, "waiting")
        self.assertEqual(res[M_PENDING].status, "pending")
        self.assertEqual(res[M_SETTLED].status, "settled")

    def test_resolved_market_archives_value(self):
        w, sink = _watcher(_markets())
        w.tick()
        self.assertEqual(w.resolver.resolved, [M_READY])
        [report] = sink.reports
        self.assertEqual(report.market_id, M_READY)
        self.assertEqual(report.kind, "scalar")
        self.assertEqual(report.answer, 4200)  # the settled value, not an outcome
        self.assertEqual(report.feed, "ETH/USD")


class ScalarDisputeWindowTests(unittest.TestCase):
    WINDOW = 3600

    def test_open_market_is_proposed_not_archived(self):
        markets = [Market(M_READY, NOW - DAY, Status.Open, feed="ETH/USD")]
        w, sink = _watcher(markets, window=self.WINDOW)
        [r] = w.tick()
        self.assertEqual(r.status, "proposed")
        self.assertEqual(w.resolver.resolved, [M_READY])  # propose tx sent
        self.assertEqual(w.resolver.finalized, [])
        self.assertEqual(sink.reports, [])  # NOT archived until finalized

    def test_closed_inside_window_waits(self):
        markets = [Market(M_READY, NOW - DAY, Status.Closed, proposed_at=NOW - 100, feed="ETH/USD")]
        w, _ = _watcher(markets, window=self.WINDOW)
        [r] = w.tick()
        self.assertEqual(r.status, "waiting")
        self.assertEqual(w.resolver.finalized, [])

    def test_closed_after_window_finalizes_and_archives_value(self):
        markets = [Market(M_READY, NOW - DAY, Status.Closed,
                          proposed_at=NOW - 2 * self.WINDOW, feed="ETH/USD")]
        w, sink = _watcher(markets, window=self.WINDOW)
        [r] = w.tick()
        self.assertEqual(r.status, "finalized")
        self.assertEqual(w.resolver.finalized, [M_READY])
        self.assertEqual(sink.reports[0].answer, 4200)
        self.assertEqual(sink.reports[0].kind, "scalar")

    def test_finalize_revert_is_reported_not_crash(self):
        class Reverting(DryRunResolver):
            def finalize(self, market_id):
                raise RuntimeError("ENGINE: disputed")

        markets = [Market(M_READY, NOW - DAY, Status.Closed, proposed_at=NOW - 2 * self.WINDOW)]
        sink = LogReportSink()
        w = ScalarWatcher(Reverting(), StubScalarOracleView({M_READY: (True, 4200)}),
                          StaticMarketSource(markets), sink, now_fn=lambda: NOW,
                          challenge_window=self.WINDOW)
        [r] = w.tick()
        self.assertEqual(r.status, "error")
        self.assertIn("disputed", r.detail)


if __name__ == "__main__":
    unittest.main()
