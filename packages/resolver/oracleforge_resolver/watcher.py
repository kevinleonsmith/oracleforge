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
from .oracle import OracleView
from .planner import plan
from .sources import MarketSource

logger = logging.getLogger("oracleforge.resolver")


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
