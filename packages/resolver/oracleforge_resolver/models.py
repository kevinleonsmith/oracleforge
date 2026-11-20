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
    WAIT = "wait"        # not yet past closeAt
    PENDING = "pending"  # closed, but oracle not ready
    RESOLVE = "resolve"  # closed and oracle ready -> poke resolve()
    SETTLED = "settled"  # already Resolved/Invalid on-chain


@dataclass
class Market:
    market_id: str
    close_at: int
    status: Status
    outcome: int = 0
    feed: str = ""
    question: str = ""


@dataclass
class Decision:
    market_id: str
    action: Action
    predicted_outcome: Optional[int] = None  # 1=YES 0=NO None=invalid/n-a
    reason: str = ""


@dataclass
class OracleReport:
    """Archival record of a settlement (destined for Tableland + Arweave)."""

    market_id: str
    outcome: int            # 1=YES 0=NO ; -1 for invalid/voided
    resolved_at: int
    feed: str = ""
    tx_hash: str = ""
    answer: Optional[int] = None
