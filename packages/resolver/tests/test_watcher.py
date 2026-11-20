"""Watcher orchestration tests (no chain/network)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from oracleforge_resolver.archive import LogReportSink  # noqa: E402
from oracleforge_resolver.chain import DryRunResolver  # noqa: E402
from oracleforge_resolver.models import Market, Outcome, Status  # noqa: E402
from oracleforge_resolver.oracle import StubOracleView  # noqa: E402
from oracleforge_resolver.sources import StaticMarketSource  # noqa: E402
from oracleforge_resolver.watcher import Watcher  # noqa: E402

NOW = 1_800_000_000
DAY = 86400

M_YES = "0x" + "a1" * 32
M_NO = "0x" + "b2" * 32
M_WAIT = "0x" + "c3" * 32
M_PENDING = "0x" + "d4" * 32
M_SETTLED = "0x" + "e5" * 32


def _markets():
    return [
        Market(M_YES, NOW - DAY, Status.Open, feed="EUR/USD"),
        Market(M_NO, NOW - DAY, Status.Open, feed="ECON/CPI"),
        Market(M_WAIT, NOW + 5 * DAY, Status.Open),
        Market(M_PENDING, NOW - DAY, Status.Open),
        Market(M_SETTLED, NOW - 2 * DAY, Status.Resolved, outcome=1),
    ]


def _watcher(markets):
    outcomes = {M_YES: Outcome.Yes, M_NO: Outcome.No, M_PENDING: Outcome.Pending}
    sink = LogReportSink()
    w = Watcher(DryRunResolver(), StubOracleView(outcomes),
                StaticMarketSource(markets), sink, now_fn=lambda: NOW)
    return w, sink


class TickTests(unittest.TestCase):
    def test_tick_classifies_each_market(self):
        w, sink = _watcher(_markets())
        res = {r.market_id: r for r in w.tick()}
        self.assertEqual(res[M_YES].status, "resolved")
        self.assertEqual(res[M_NO].status, "resolved")
        self.assertEqual(res[M_WAIT].status, "waiting")
        self.assertEqual(res[M_PENDING].status, "pending")
        self.assertEqual(res[M_SETTLED].status, "settled")

    def test_only_ready_markets_resolve(self):
        w, _ = _watcher(_markets())
        w.tick()
        self.assertEqual(sorted(w.resolver.resolved), sorted([M_YES, M_NO]))

    def test_reports_archived_with_outcome(self):
        w, sink = _watcher(_markets())
        w.tick()
        by_id = {r.market_id: r for r in sink.reports}
        self.assertEqual(by_id[M_YES].outcome, 1)
        self.assertEqual(by_id[M_NO].outcome, 0)
        self.assertEqual(by_id[M_YES].feed, "EUR/USD")
        self.assertTrue(by_id[M_YES].tx_hash.startswith("0x"))

    def test_invalid_outcome_archived_as_void(self):
        markets = [Market(M_YES, NOW - DAY, Status.Open, feed="FUNCTIONS/NOAA")]
        sink = LogReportSink()
        w = Watcher(DryRunResolver(), StubOracleView({M_YES: Outcome.Invalid}),
                    StaticMarketSource(markets), sink, now_fn=lambda: NOW)
        [r] = w.tick()
        self.assertEqual(r.status, "resolved")
        self.assertEqual(sink.reports[0].outcome, -1)  # void


class IdempotencyTests(unittest.TestCase):
    def test_pending_then_ready_resolves_once(self):
        # tick 1: oracle pending -> no resolve
        markets = [Market(M_YES, NOW - DAY, Status.Open, feed="EUR/USD")]
        outcomes = {M_YES: Outcome.Pending}
        view = StubOracleView(outcomes)
        resolver = DryRunResolver()
        w = Watcher(resolver, view, StaticMarketSource(markets), LogReportSink(), now_fn=lambda: NOW)
        self.assertEqual(w.tick()[0].status, "pending")
        self.assertEqual(resolver.resolved, [])

        # oracle becomes ready -> resolves on the next tick
        outcomes[M_YES] = Outcome.Yes
        self.assertEqual(w.tick()[0].status, "resolved")
        self.assertEqual(resolver.resolved, [M_YES])

    def test_double_resolve_reported_as_error_not_crash(self):
        class Reverting(DryRunResolver):
            def resolve(self, market_id):
                raise RuntimeError("ENGINE: settled")

        markets = [Market(M_YES, NOW - DAY, Status.Open)]
        w = Watcher(Reverting(), StubOracleView({M_YES: Outcome.Yes}),
                    StaticMarketSource(markets), LogReportSink(), now_fn=lambda: NOW)
        [r] = w.tick()
        self.assertEqual(r.status, "error")
        self.assertIn("settled", r.detail)


class DisputeWindowTests(unittest.TestCase):
    """With a challenge window, resolve() only proposes (no archive yet) and a
    separate finalize() settles it after the window elapses."""

    WINDOW = 3600

    def test_open_market_is_proposed_not_archived(self):
        markets = [Market(M_YES, NOW - DAY, Status.Open, feed="EUR/USD")]
        sink = LogReportSink()
        resolver = DryRunResolver()
        w = Watcher(resolver, StubOracleView({M_YES: Outcome.Yes}),
                    StaticMarketSource(markets), sink, now_fn=lambda: NOW,
                    challenge_window=self.WINDOW)
        [r] = w.tick()
        self.assertEqual(r.status, "proposed")
        self.assertEqual(resolver.resolved, [M_YES])  # propose tx sent
        self.assertEqual(resolver.finalized, [])
        self.assertEqual(sink.reports, [])            # NOT archived until finalized

    def test_closed_inside_window_waits(self):
        markets = [Market(M_YES, NOW - DAY, Status.Closed, proposed_at=NOW - 100, feed="EUR/USD")]
        resolver = DryRunResolver()
        w = Watcher(resolver, StubOracleView({M_YES: Outcome.Yes}),
                    StaticMarketSource(markets), LogReportSink(), now_fn=lambda: NOW,
                    challenge_window=self.WINDOW)
        [r] = w.tick()
        self.assertEqual(r.status, "waiting")
        self.assertEqual(resolver.finalized, [])

    def test_closed_after_window_finalizes_and_archives(self):
        markets = [Market(M_YES, NOW - DAY, Status.Closed, proposed_at=NOW - 2 * self.WINDOW,
                          feed="EUR/USD")]
        sink = LogReportSink()
        resolver = DryRunResolver()
        w = Watcher(resolver, StubOracleView({M_YES: Outcome.Yes}),
                    StaticMarketSource(markets), sink, now_fn=lambda: NOW,
                    challenge_window=self.WINDOW)
        [r] = w.tick()
        self.assertEqual(r.status, "finalized")
        self.assertEqual(resolver.finalized, [M_YES])
        self.assertEqual(sink.reports[0].outcome, 1)       # archived at finalization
        self.assertTrue(sink.reports[0].tx_hash.startswith("0x"))

    def test_finalize_revert_is_reported_not_crash(self):
        class Reverting(DryRunResolver):
            def finalize(self, market_id):
                raise RuntimeError("ENGINE: disputed")

        markets = [Market(M_YES, NOW - DAY, Status.Closed, proposed_at=NOW - 2 * self.WINDOW)]
        w = Watcher(Reverting(), StubOracleView({M_YES: Outcome.Yes}),
                    StaticMarketSource(markets), LogReportSink(), now_fn=lambda: NOW,
                    challenge_window=self.WINDOW)
        [r] = w.tick()
        self.assertEqual(r.status, "error")
        self.assertIn("disputed", r.detail)


if __name__ == "__main__":
    unittest.main()
