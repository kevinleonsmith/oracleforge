"""Core data structures shared across the pipeline."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass(frozen=True)
class Signal:
    """A single real-world observation ingested from a source."""

    source: str  # "news" | "macro" | "crypto" | "climate" | "geopolitics" ...
    topic: str  # short semantic topic label
    text: str  # headline / summary text
    weight: float = 1.0  # source reliability weight in [0,1]
    ts: int = 0  # unix seconds


@dataclass
class OracleSpec:
    """Resolution spec the engine passes to the Chainlink oracle adapter.

    Mirrors ``ChainlinkOracleAdapter.configure`` abi.encode layout:
      (feed, fallbackFeed, threshold, comparator, maxStale)
    """

    feed: str  # feed address or symbolic id ("EUR/USD")
    threshold: int  # scaled int (feed decimals)
    comparator: int  # 0 => answer >= threshold is YES ; 1 => <=
    fallback_feed: str = "0x0000000000000000000000000000000000000000"
    max_stale: int = 3600


@dataclass
class MarketProposal:
    """A candidate market emitted by the generator, ready for on-chain creation."""

    question: str
    category: str
    close_at: int  # unix seconds
    ai_prob_bps: int  # 0..10000 initialized YES probability
    confidence: float  # 0..1 aggregate confidence
    confidence_by_source: dict = field(default_factory=dict)
    oracle: Optional[OracleSpec] = None
    evidence: list = field(default_factory=list)  # signal texts backing the market
    cluster_id: int = -1

    @property
    def question_hash(self) -> str:
        """keccak-less canonical hash (sha256) of the question text.

        The on-chain engine keys markets by keccak256(question); off-chain we use
        sha256 for the Tableland/Arweave record id. Both are derived from the
        same canonicalized text so they stay joinable.
        """
        canon = " ".join(self.question.lower().split())
        return "0x" + hashlib.sha256(canon.encode()).hexdigest()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["question_hash"] = self.question_hash
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)
