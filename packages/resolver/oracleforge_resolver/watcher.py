"""Watcher orchestration: discover -> plan -> resolve -> archive.

One ``tick()`` scans the source once and acts. ``watch()`` loops on an interval.
The resolve() call is permissionless, so many watchers can run safely — the
engine simply reverts a double-resolve, which a tick reports as a benign error.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import List, Optional

from .archive import LogReportSink, ReportSink
from .chain import Resolver
from .models import Action, Market, OracleReport
from .oracle import CategoricalOracleView, OracleView, ScalarOracleView
from .planner import plan, plan_categorical, plan_scalar
from .sources import MarketSource

logger = logging.getLogger("oracleforge.resolver")


def _emit_proposal(sink, market_id: str, proposed_at: int) -> None:
    """Record the propose (OPEN -> CLOSED) catalog transition if the sink supports
    it. A plain report sink (in-memory / capturing) without ``record_proposal`` is a
    no-op, so this stays additive across every sink."""
    fn = getattr(sink, "record_proposal", None)
    if fn is not None:
        fn(market_id, proposed_at)


@dataclass
class TickOutcome:
    market_id: str
    action: str
    # "resolved" | "proposed" | "finalized" | "waiting" | "pending" | "settled" | "error"
    status: str
    detail: str = ""
    tx_hash: Optional[str] = None
    predicted_outcome: Optional[int] = None


class Watcher:
    def __init__(
        self,
        resolver: Resolver,
        oracle_view: OracleView,
        source: MarketSource,
        sink: Optional[ReportSink] = None,
        now_fn=None,
        challenge_window: int = 0,
    ):
        self.resolver = resolver
        self.oracle_view = oracle_view
        self.source = source
        self.sink = sink or LogReportSink()
        self._now = now_fn or (lambda: int(time.time()))
        # 0 => resolve() settles atomically (original behavior). A positive value
        # means resolve() only proposes, and finalize() settles after the window.
        self.challenge_window = challenge_window

    def tick(self) -> List[TickOutcome]:
        markets = self.source.open_markets()
        by_id = {m.market_id: m for m in markets}
        decisions = plan(markets, self._now(), self.oracle_view.outcome, self.challenge_window)

        results: List[TickOutcome] = []
        for d in decisions:
            if d.action == Action.RESOLVE:
                results.append(self._resolve(by_id[d.market_id], d.predicted_outcome, d.reason))
            elif d.action == Action.FINALIZE:
                results.append(self._finalize(by_id[d.market_id], d.predicted_outcome, d.reason))
            else:
                results.append(
                    TickOutcome(d.market_id, d.action.value,
                                {"wait": "waiting", "pending": "pending",
                                 "settled": "settled"}[d.action.value], d.reason)
                )
        counts: dict = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        logger.info("tick: %s", counts)
        return results

    def _archive(self, market: Market, predicted, tx: str) -> None:
        self.sink.record(OracleReport(
            market_id=market.market_id,
            outcome=predicted if predicted is not None else -1,  # -1 = invalid/void
            resolved_at=self._now(),
            feed=market.feed,
            tx_hash=tx,
        ))

    def _resolve(self, market: Market, predicted, reason: str) -> TickOutcome:
        try:
            tx = self.resolver.resolve(market.market_id)
        except Exception as e:  # noqa: BLE001 - a revert (e.g. double-resolve) is non-fatal
            return TickOutcome(market.market_id, "resolve", "error",
                               f"{type(e).__name__}: {e}", predicted_outcome=predicted)
        # With a challenge window the outcome is only *proposed* and can still be
        # disputed, so we don't archive it as settled yet — finalize() does that.
        if self.challenge_window > 0:
            _emit_proposal(self.sink, market.market_id, self._now())
            return TickOutcome(market.market_id, "resolve", "proposed", reason, tx, predicted)
        self._archive(market, predicted, tx)
        return TickOutcome(market.market_id, "resolve", "resolved", reason, tx, predicted)

    def _finalize(self, market: Market, predicted, reason: str) -> TickOutcome:
        try:
            tx = self.resolver.finalize(market.market_id)
        except Exception as e:  # noqa: BLE001 - a revert (window open / disputed) is non-fatal
            return TickOutcome(market.market_id, "finalize", "error",
                               f"{type(e).__name__}: {e}", predicted_outcome=predicted)
        self._archive(market, predicted, tx)
        return TickOutcome(market.market_id, "finalize", "finalized", reason, tx, predicted)

    def watch(self, interval: float = 30.0, max_ticks: Optional[int] = None) -> None:
        n = 0
        while True:
            self.tick()
            n += 1
            if max_ticks is not None and n >= max_ticks:
                return
            time.sleep(interval)


class ScalarWatcher:
    """Watcher for scalar (range) markets. Same orchestration as Watcher, driving
    the shared resolve()/finalize() on a ScalarMarketEngine, but it plans from the
    scalar oracle's ``(ready, value)`` and archives the settled value."""

    def __init__(
        self,
        resolver: Resolver,
        oracle_view: ScalarOracleView,
        source: MarketSource,
        sink: Optional[ReportSink] = None,
        now_fn=None,
        challenge_window: int = 0,
    ):
        self.resolver = resolver
        self.oracle_view = oracle_view
        self.source = source
        self.sink = sink or LogReportSink()
        self._now = now_fn or (lambda: int(time.time()))
        self.challenge_window = challenge_window

    def tick(self) -> List[TickOutcome]:
        markets = self.source.open_markets()
        by_id = {m.market_id: m for m in markets}
        decisions = plan_scalar(markets, self._now(), self.oracle_view.value, self.challenge_window)

        results: List[TickOutcome] = []
        for d in decisions:
            if d.action == Action.RESOLVE:
                results.append(self._resolve(by_id[d.market_id], d.predicted_value, d.reason))
            elif d.action == Action.FINALIZE:
                results.append(self._finalize(by_id[d.market_id], d.predicted_value, d.reason))
            else:
                results.append(
                    TickOutcome(d.market_id, d.action.value,
                                {"wait": "waiting", "pending": "pending",
                                 "settled": "settled"}[d.action.value], d.reason)
                )
        counts: dict = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        logger.info("scalar tick: %s", counts)
        return results

    def _archive(self, market: Market, value, tx: str) -> None:
        self.sink.record(OracleReport(
            market_id=market.market_id,
            outcome=0,  # not meaningful for scalar
            resolved_at=self._now(),
            feed=market.feed,
            tx_hash=tx,
            answer=value,  # the settled (clamped) value
            kind="scalar",
        ))

    def _resolve(self, market: Market, value, reason: str) -> TickOutcome:
        try:
            tx = self.resolver.resolve(market.market_id)
        except Exception as e:  # noqa: BLE001 - a revert (double-resolve) is non-fatal
            return TickOutcome(market.market_id, "resolve", "error", f"{type(e).__name__}: {e}")
        # Under a window the value is only proposed and may still be disputed, so
        # we don't archive it yet — finalize() does.
        if self.challenge_window > 0:
            _emit_proposal(self.sink, market.market_id, self._now())
            return TickOutcome(market.market_id, "resolve", "proposed", reason, tx)
        self._archive(market, value, tx)
        return TickOutcome(market.market_id, "resolve", "resolved", reason, tx)

    def _finalize(self, market: Market, value, reason: str) -> TickOutcome:
        try:
            tx = self.resolver.finalize(market.market_id)
        except Exception as e:  # noqa: BLE001 - a revert (window open / disputed) is non-fatal
            return TickOutcome(market.market_id, "finalize", "error", f"{type(e).__name__}: {e}")
        self._archive(market, value, tx)
        return TickOutcome(market.market_id, "finalize", "finalized", reason, tx)

    def watch(self, interval: float = 30.0, max_ticks: Optional[int] = None) -> None:
        n = 0
        while True:
            self.tick()
            n += 1
            if max_ticks is not None and n >= max_ticks:
                return
            time.sleep(interval)


class CategoricalWatcher:
    """Watcher for categorical (N-outcome) markets. Same orchestration as Watcher,
    driving the shared resolve()/finalize() on a CategoricalMarketEngine, but it
    plans from the categorical oracle's ``(ready, winning index)`` and archives the
    winning outcome index (or -1 for a void)."""

    def __init__(
        self,
        resolver: Resolver,
        oracle_view: CategoricalOracleView,
        source: MarketSource,
        sink: Optional[ReportSink] = None,
        now_fn=None,
        challenge_window: int = 0,
    ):
        self.resolver = resolver
        self.oracle_view = oracle_view
        self.source = source
        self.sink = sink or LogReportSink()
        self._now = now_fn or (lambda: int(time.time()))
        self.challenge_window = challenge_window

    def tick(self) -> List[TickOutcome]:
        markets = self.source.open_markets()
        by_id = {m.market_id: m for m in markets}
        decisions = plan_categorical(
            markets, self._now(), self.oracle_view.winning_outcome, self.challenge_window
        )

        results: List[TickOutcome] = []
        for d in decisions:
            if d.action == Action.RESOLVE:
                results.append(self._resolve(by_id[d.market_id], d.predicted_outcome, d.reason))
            elif d.action == Action.FINALIZE:
                results.append(self._finalize(by_id[d.market_id], d.predicted_outcome, d.reason))
            else:
                results.append(
                    TickOutcome(d.market_id, d.action.value,
                                {"wait": "waiting", "pending": "pending",
                                 "settled": "settled"}[d.action.value], d.reason,
                                predicted_outcome=d.predicted_outcome)
                )
        counts: dict = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        logger.info("categorical tick: %s", counts)
        return results

    def _archive(self, market: Market, predicted, tx: str) -> None:
        self.sink.record(OracleReport(
            market_id=market.market_id,
            outcome=predicted if predicted is not None else -1,  # -1 = invalid/void
            resolved_at=self._now(),
            feed=market.feed,
            tx_hash=tx,
            kind="categorical",
        ))

    def _resolve(self, market: Market, predicted, reason: str) -> TickOutcome:
        try:
            tx = self.resolver.resolve(market.market_id)
        except Exception as e:  # noqa: BLE001 - a revert (double-resolve) is non-fatal
            return TickOutcome(market.market_id, "resolve", "error",
                               f"{type(e).__name__}: {e}", predicted_outcome=predicted)
        # Under a window the outcome is only proposed and may still be disputed, so
        # we don't archive it yet — finalize() does.
        if self.challenge_window > 0:
            _emit_proposal(self.sink, market.market_id, self._now())
            return TickOutcome(market.market_id, "resolve", "proposed", reason, tx, predicted)
        self._archive(market, predicted, tx)
        return TickOutcome(market.market_id, "resolve", "resolved", reason, tx, predicted)

    def _finalize(self, market: Market, predicted, reason: str) -> TickOutcome:
        try:
            tx = self.resolver.finalize(market.market_id)
        except Exception as e:  # noqa: BLE001 - a revert (window open / disputed) is non-fatal
            return TickOutcome(market.market_id, "finalize", "error",
                               f"{type(e).__name__}: {e}", predicted_outcome=predicted)
        self._archive(market, predicted, tx)
        return TickOutcome(market.market_id, "finalize", "finalized", reason, tx, predicted)

    def watch(self, interval: float = 30.0, max_ticks: Optional[int] = None) -> None:
        n = 0
        while True:
            self.tick()
            n += 1
            if max_ticks is not None and n >= max_ticks:
                return
            time.sleep(interval)
