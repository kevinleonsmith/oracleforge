"""Pure resolution planning — the heart of the watcher, no I/O.

Given a market's state and the current time, decide what to do. The oracle is
queried lazily (only for markets that are closed and not yet settled) via the
``outcome_fn`` callback, so a live watcher makes the minimum number of oracle
reads.
"""
from __future__ import annotations

from typing import Callable, List

from .models import Action, Decision, Market, Outcome, Status

# Called only when a market is closed and unsettled: market_id -> Outcome.
OutcomeFn = Callable[[str], Outcome]


def _predicted_outcome(o: Outcome):
    if o == Outcome.Yes:
        return 1, "oracle ready: YES"
    if o == Outcome.No:
        return 0, "oracle ready: NO"
    return None, "oracle ready: INVALID (void)"


def plan_one(
    market: Market, now: int, outcome_fn: OutcomeFn, challenge_window: int = 0
) -> Decision:
    if market.status in (Status.Resolved, Status.Invalid):
        return Decision(market.market_id, Action.SETTLED, reason="already settled")

    # A proposed outcome (Status.Closed) is in its challenge window: wait it out,
    # then finalize(). The engine stored the proposal, so the oracle read here is
    # just to label the archival record (it matches the proposal on the common,
    # un-arbitrated path). With challenge_window == 0 the engine finalizes inside
    # resolve(), so a market is never observed Closed and this branch is inert.
    if market.status == Status.Closed:
        deadline = market.proposed_at + challenge_window
        if now < deadline:
            return Decision(
                market.market_id, Action.WAIT,
                reason=f"challenge window: {deadline - now}s left",
            )
        predicted, label = _predicted_outcome(outcome_fn(market.market_id))
        return Decision(
            market.market_id, Action.FINALIZE, predicted_outcome=predicted,
            reason=f"window elapsed -> finalize ({label})",
        )

    if now < market.close_at:
        return Decision(
            market.market_id, Action.WAIT,
            reason=f"closes in {market.close_at - now}s",
        )

    # past close and unsettled -> ask the oracle whether it can resolve yet
    o = outcome_fn(market.market_id)
    if o == Outcome.Pending:
        return Decision(market.market_id, Action.PENDING, reason="oracle feed not ready")

    predicted, reason = _predicted_outcome(o)
    return Decision(market.market_id, Action.RESOLVE, predicted_outcome=predicted, reason=reason)


def plan(
    markets: List[Market], now: int, outcome_fn: OutcomeFn, challenge_window: int = 0
) -> List[Decision]:
    return [plan_one(m, now, outcome_fn, challenge_window) for m in markets]
