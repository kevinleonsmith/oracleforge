"""Core types for the resolution watcher."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Optional


class Status(IntEnum):
    """Mirrors MarketEngine.Status."""

    Open = 0
    Closed = 1
    Resolved = 2
    Invalid = 3


class Outcome(IntEnum):
    """Mirrors IOracleAdapter.Outcome."""

    Pending = 0
    Yes = 1
    No = 2
    Invalid = 3


_STATUS_BY_NAME = {s.name.upper(): s for s in Status}


def status_from(value) -> Status:
    """Normalize a status from Tableland text ('OPEN') or a chain int."""
    if isinstance(value, Status):
        return value
    if isinstance(value, int):
        return Status(value)
    return _STATUS_BY_NAME[str(value).upper()]


class Action(Enum):
    WAIT = "wait"          # not yet past closeAt, or inside the challenge window
    PENDING = "pending"    # closed, but oracle not ready
    RESOLVE = "resolve"    # past close and oracle ready -> propose resolve()
    FINALIZE = "finalize"  # proposed, challenge window elapsed -> finalize()
    SETTLED = "settled"    # already Resolved/Invalid on-chain


@dataclass
class Market:
    market_id: str
    close_at: int
    status: Status
    outcome: int = 0
    feed: str = ""
    question: str = ""
    proposed_at: int = 0  # when the outcome was proposed (Status.Closed); 0 if not


@dataclass
class Decision:
    market_id: str
    action: Action
    predicted_outcome: Optional[int] = None  # binary: 1=YES 0=NO None=invalid/n-a
    predicted_value: Optional[int] = None  # scalar: proposed settlement value
    reason: str = ""


@dataclass
class OracleReport:
    """Archival record of a settlement (destined for Tableland + Arweave)."""

    market_id: str
    outcome: int            # binary: 1=YES 0=NO ; -1 for invalid/voided (scalar: unused, 0)
    resolved_at: int
    feed: str = ""
    tx_hash: str = ""
    answer: Optional[int] = None  # raw oracle answer; the settled value for scalar markets
    kind: str = "binary"    # "binary" | "scalar"
