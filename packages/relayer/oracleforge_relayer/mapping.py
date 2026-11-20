"""Pure mapping: AI proposal + committed forecast -> createMarket arguments.

No chain or network imports, so this is fully unit-tested. The ``ai_prob_bps``
used is the one COMMITTED by the Cartesi notice (verifiable), not the generator's
local guess — they are computed by the same deterministic function and should
match, but the on-chain value must be the committed one.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from . import abi
from .feeds import FeedRegistry


class SkipProposal(Exception):
    """Raised when a proposal cannot be turned into a valid on-chain creation."""


@dataclass
class CreateMarketArgs:
    question: str
    question_hash: str  # keccak256(question) — on-chain bytes32
    close_at: int
    ai_prob_bps: int
    oracle_params: str  # 0x-encoded bytes for createMarket
    market_id: str  # predicted id (for dedupe/logging)
    feed: str

    def as_tx_args(self) -> list:
        """Positional args for MarketEngine.createMarket."""
        return [self.question_hash, self.close_at, self.ai_prob_bps, self.oracle_params]


def build_create_market_args(
    proposal: Dict[str, Any],
    committed_prob_bps: int,
    chain_id: int,
    registry: FeedRegistry,
    now_ts: int,
) -> CreateMarketArgs:
    if not 0 <= committed_prob_bps <= 10_000:
        raise SkipProposal(f"prob_bps out of range: {committed_prob_bps}")

    question = proposal.get("question")
    close_at = proposal.get("close_at")
    oracle = proposal.get("oracle")
    if not question or close_at is None or not oracle:
        raise SkipProposal("proposal missing question/close_at/oracle")

    if close_at <= now_ts:
        raise SkipProposal(f"close_at in the past ({close_at} <= {now_ts})")

    feed_addr = registry.resolve(oracle["feed"])
    if feed_addr is None:
        raise SkipProposal(f"no resolver address for feed {oracle['feed']!r}")

    comparator = int(oracle.get("comparator", 0))
    params = abi.encode_oracle_params(
        feed=feed_addr,
        fallback_feed=oracle.get("fallback_feed") or registry.zero,
        threshold=int(oracle["threshold"]),
        comparator=comparator,
        max_stale=int(oracle.get("max_stale", 3600)),
    )

    qhash = abi.question_hash(question)
    mid = abi.market_id(qhash, int(close_at), chain_id)

    return CreateMarketArgs(
        question=question,
        question_hash=qhash,
        close_at=int(close_at),
        ai_prob_bps=int(committed_prob_bps),
        oracle_params=params,
        market_id=mid,
        feed=feed_addr,
    )
