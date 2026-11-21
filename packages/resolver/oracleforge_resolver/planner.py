"""Pure resolution planning — the heart of the watcher, no I/O.

Given a market's state and the current time, decide what to do. The oracle is
queried lazily (only for markets that are closed and not yet settled) via the
``outcome_fn`` callback, so a live watcher makes the minimum number of oracle
reads.
"""
from __future__ import annotations

from typing import Callable, List, Tuple

from .models import Action, Decision, Market, Outcome, Status

# Called only when a market is closed and unsettled: market_id -> Outcome.
OutcomeFn = Callable[[str], Outcome]
# Scalar equivalent: market_id -> (ready, value).
ValueFn = Callable[[str], Tuple[bool, int]]
# Categorical equivalent: market_id -> (ready, winning outcome index).
WinningOutcomeFn = Callable[[str], Tuple[bool, int]]

# The engine's out-of-range sentinel: an oracle outcome at or above this signals an
# invalid/cancelled market (a void). Valid outcome indices are 0..outcomeCount-1,
# and the engine caps outcomeCount at 64, so 0xFF can never be a real index.
INVALID_OUTCOME = 0xFF


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


# ----------------------------------------------------------------- scalar markets


def plan_scalar_one(
    market: Market, now: int, value_fn: ValueFn, challenge_window: int = 0
) -> Decision:
    """Scalar analogue of plan_one. Identical lifecycle — the only difference is
    that readiness and the proposed payload come from the scalar oracle's
    ``(ready, value)`` instead of a yes/no Outcome. The ScalarMarketEngine shares
    resolve()/finalize() and the Open->Closed->Resolved status flow, so the
    decisions (WAIT/PENDING/RESOLVE/FINALIZE/SETTLED) carry straight over."""
    if market.status in (Status.Resolved, Status.Invalid):
        return Decision(market.market_id, Action.SETTLED, reason="already settled")

    # Proposed value in its challenge window: wait it out, then finalize(). The
    # engine already stored the clamped value; the read here just labels the
    # archival record. Inert when challenge_window == 0 (resolve finalizes inline).
    if market.status == Status.Closed:
        deadline = market.proposed_at + challenge_window
        if now < deadline:
            return Decision(
                market.market_id, Action.WAIT,
                reason=f"challenge window: {deadline - now}s left",
            )
        _, value = value_fn(market.market_id)
        return Decision(
            market.market_id, Action.FINALIZE, predicted_value=value,
            reason=f"window elapsed -> finalize (value={value})",
        )

    if now < market.close_at:
        return Decision(
            market.market_id, Action.WAIT,
            reason=f"closes in {market.close_at - now}s",
        )

    # past close and unsettled -> ask the scalar oracle whether a value is ready
    ready, value = value_fn(market.market_id)
    if not ready:
        return Decision(market.market_id, Action.PENDING, reason="oracle feed not ready")

    return Decision(
        market.market_id, Action.RESOLVE, predicted_value=value,
        reason=f"oracle ready: value={value}",
    )


def plan_scalar(
    markets: List[Market], now: int, value_fn: ValueFn, challenge_window: int = 0
) -> List[Decision]:
    return [plan_scalar_one(m, now, value_fn, challenge_window) for m in markets]


# ------------------------------------------------------------ categorical markets


def _predicted_categorical(outcome: int):
    """Map a winning outcome index to (predicted, label). The out-of-range
    sentinel (>= INVALID_OUTCOME) is a void, signalled as predicted=None — the
    same convention the binary planner uses for Outcome.Invalid."""
    if outcome >= INVALID_OUTCOME:
        return None, "oracle ready: INVALID (void)"
    return outcome, f"oracle ready: outcome {outcome}"


def plan_categorical_one(
    market: Market, now: int, outcome_fn: WinningOutcomeFn, challenge_window: int = 0
) -> Decision:
    """Categorical analogue of plan_one. Identical lifecycle — the only difference
    is that readiness and the proposed payload come from the categorical oracle's
    ``(ready, winning index)`` instead of a yes/no Outcome. The
    CategoricalMarketEngine shares resolve()/finalize() and the
    Open->Closed->Resolved status flow, so the decisions carry straight over."""
    if market.status in (Status.Resolved, Status.Invalid):
        return Decision(market.market_id, Action.SETTLED, reason="already settled")

    # Proposed outcome in its challenge window: wait it out, then finalize(). The
    # engine already stored the proposed index; the read here just labels the
    # archival record. Inert when challenge_window == 0 (resolve finalizes inline).
    if market.status == Status.Closed:
        deadline = market.proposed_at + challenge_window
        if now < deadline:
            return Decision(
                market.market_id, Action.WAIT,
                reason=f"challenge window: {deadline - now}s left",
            )
        _, outcome = outcome_fn(market.market_id)
        predicted, label = _predicted_categorical(outcome)
        return Decision(
            market.market_id, Action.FINALIZE, predicted_outcome=predicted,
            reason=f"window elapsed -> finalize ({label})",
        )

    if now < market.close_at:
        return Decision(
            market.market_id, Action.WAIT,
            reason=f"closes in {market.close_at - now}s",
        )

    # past close and unsettled -> ask the categorical oracle for the winning index
    ready, outcome = outcome_fn(market.market_id)
    if not ready:
        return Decision(market.market_id, Action.PENDING, reason="oracle feed not ready")

    predicted, reason = _predicted_categorical(outcome)
    return Decision(
        market.market_id, Action.RESOLVE, predicted_outcome=predicted, reason=reason
    )


def plan_categorical(
    markets: List[Market], now: int, outcome_fn: WinningOutcomeFn, challenge_window: int = 0
) -> List[Decision]:
    return [plan_categorical_one(m, now, outcome_fn, challenge_window) for m in markets]
