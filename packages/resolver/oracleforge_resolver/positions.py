"""Positions indexer — fill the ``positions`` table from PositionTaken events.

The relayer indexes markets/predictions at creation and the resolver indexes
oracle_reports + the markets catalog at settlement; between them, trades happen —
``takePosition`` emits ``PositionTaken(marketId, account, side, amount)`` on each
engine. Nothing watched those, so ``positions`` was the one index table with no
writer. This closes that: an event source yields the logs, a pure row builder turns
each into a ``positions`` INSERT, and a ``TablelandMutator`` (shared with the
settlement write-back) sends it — logged in dry-run, signed on the live path.

``side`` is a plain integer that generalises across engines: binary YES/NO (1/0),
scalar LONG/SHORT (1/0), and the categorical winning-outcome index (0..N-1) — the
same column serves all three, as it does in the schema.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol

from .archive import LogTablelandMutator, TablelandMutator, _q

logger = logging.getLogger("oracleforge.resolver.positions")

DEFAULT_POSITIONS_TABLE = "positions"


@dataclass
class PositionEvent:
    """A decoded ``PositionTaken`` log (engine-agnostic)."""

    market_id: str
    account: str
    side: int          # binary YES/NO 1/0 · scalar LONG/SHORT 1/0 · categorical index
    amount: int        # staked base units
    tx_hash: str
    created_at: int    # block timestamp

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PositionEvent":
        return cls(
            market_id=str(d["market_id"]),
            account=str(d["account"]),
            side=int(d["side"]),
            amount=int(d["amount"]),
            tx_hash=str(d.get("tx_hash", "")),
            created_at=int(d.get("created_at", 0)),
        )


@dataclass
class PositionRow:
    """One ``positions`` row. ``claimed`` starts 0 and is flipped by a later claim
    (a separate write, like the markets status transitions). ``amount`` is a uint256
    stored as a decimal string, matching the schema."""

    market_id: str
    account: str
    side: int
    amount: int
    tx_hash: str
    created_at: int
    claimed: int = 0

    @classmethod
    def from_event(cls, e: PositionEvent) -> "PositionRow":
        return cls(
            market_id=e.market_id, account=e.account, side=e.side,
            amount=e.amount, tx_hash=e.tx_hash, created_at=e.created_at,
        )

    def sql(self, table: str = DEFAULT_POSITIONS_TABLE) -> str:
        cols = ["market_id", "account", "side", "amount", "claimed", "tx_hash", "created_at"]
        vals = [_q(self.market_id), _q(self.account), str(self.side),
                _q(str(self.amount)), str(self.claimed), _q(self.tx_hash), str(self.created_at)]
        return f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(vals)});"


@dataclass
class ClaimEvent:
    """A decoded ``Claimed`` log: an account withdrew its winnings/refund for a
    market. In these engines a claim settles the account's whole stake at once, so
    it marks every one of that account's positions in the market as claimed."""

    market_id: str
    account: str

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ClaimEvent":
        return cls(market_id=str(d["market_id"]), account=str(d["account"]))


@dataclass
class PositionClaimUpdate:
    """Flip ``claimed`` on an account's positions once it has claimed — the
    positions-side catalog transition, mirroring the markets status UPDATEs. Without
    it the index would show a settled, withdrawn position as still open (unclaimed)."""

    market_id: str
    account: str

    @classmethod
    def from_event(cls, e: ClaimEvent) -> "PositionClaimUpdate":
        return cls(market_id=e.market_id, account=e.account)

    def sql(self, table: str = DEFAULT_POSITIONS_TABLE) -> str:
        return (
            f"UPDATE {table} SET claimed=1 "
            f"WHERE market_id={_q(self.market_id)} AND account={_q(self.account)};"
        )


class PositionEventSource(Protocol):
    def events(self) -> List[PositionEvent]: ...


class StubPositionEventSource:
    """A fixed list of events for dev/CI/dry-run (no chain)."""

    def __init__(self, events: List[PositionEvent]):
        self._events = list(events)

    def events(self) -> List[PositionEvent]:
        return list(self._events)


class ChainPositionEventSource:
    """Reads PositionTaken logs from an engine via web3. The live path."""

    def __init__(self, rpc_url: str, engine_address: str, from_block: int = 0):
        self.rpc_url = rpc_url
        self.engine_address = engine_address
        self.from_block = from_block

    def events(self) -> List[PositionEvent]:  # pragma: no cover - needs chain + web3
        raise NotImplementedError(
            "ChainPositionEventSource.events: fetch PositionTaken logs from "
            f"{self.engine_address} since block {self.from_block} and decode them"
        )


class PositionIndexer:
    """Pulls PositionTaken events and writes a ``positions`` INSERT for each through
    a ``TablelandMutator`` (``LogTablelandMutator`` by default — fully usable and
    testable without a chain; a ``RegistryTablelandMutator`` signs the live write)."""

    def __init__(self, source: PositionEventSource,
                 mutator: Optional[TablelandMutator] = None,
                 table: str = DEFAULT_POSITIONS_TABLE):
        self.source = source
        self.mutator = mutator or LogTablelandMutator()
        self.table = table
        self.rows: List[PositionRow] = []

    def index(self) -> List[PositionRow]:
        for e in self.source.events():
            row = PositionRow.from_event(e)
            self.rows.append(row)
            self.mutator.mutate(row.sql(self.table))
        logger.info("indexed %d position(s)", len(self.rows))
        return self.rows

    def index_claims(self, claims: List[ClaimEvent]) -> List[PositionClaimUpdate]:
        """Flip ``claimed`` for each Claimed event — the withdrawal transition that
        follows a trade's lifecycle, emitted through the same mutator seam."""
        updates = [PositionClaimUpdate.from_event(c) for c in claims]
        for u in updates:
            self.mutator.mutate(u.sql(self.table))
        logger.info("marked %d claim(s)", len(updates))
        return updates
