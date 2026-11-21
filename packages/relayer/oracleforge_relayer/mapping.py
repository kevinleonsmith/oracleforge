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


UINT64_MAX = (1 << 64) - 1
INT256_MIN = -(1 << 255)
INT256_MAX = (1 << 255) - 1
MAX_OUTCOMES = 64  # mirrors CategoricalMarketEngine.MAX_OUTCOMES


def _as_int(value, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise SkipProposal(f"{name} is not an integer: {value!r}")


def _uint64(value, name: str) -> int:
    n = _as_int(value, name)
    if not 0 <= n <= UINT64_MAX:
        raise SkipProposal(f"{name} out of uint64 range: {n}")
    return n


def _int256(value, name: str) -> int:
    n = _as_int(value, name)
    if not INT256_MIN <= n <= INT256_MAX:
        raise SkipProposal(f"{name} out of int256 range: {n}")
    return n


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

    # close_at is encoded as a uint64 and packed into the marketId preimage, so an
    # out-of-range value must be skipped, never submitted (it would revert or, in
    # the preimage, raise mid-flight and surface as a batch error).
    close_at = _uint64(close_at, "close_at")
    if close_at <= now_ts:
        raise SkipProposal(f"close_at in the past ({close_at} <= {now_ts})")

    feed_sym = oracle.get("feed")
    feed_addr = registry.resolve(feed_sym) if feed_sym else None
    if feed_addr is None:
        raise SkipProposal(f"no resolver address for feed {feed_sym!r}")

    # Validate the oracle params up front (clear skips), so a malformed proposal is
    # dropped rather than raising a generic error inside the ABI encoder.
    if "threshold" not in oracle:
        raise SkipProposal("oracle missing threshold")
    threshold = _int256(oracle["threshold"], "threshold")
    comparator = _as_int(oracle.get("comparator", 0), "comparator")
    if comparator not in (0, 1):
        raise SkipProposal(f"comparator must be 0 or 1, got {comparator}")
    max_stale = _uint64(oracle.get("max_stale", 3600), "max_stale")

    params = abi.encode_oracle_params(
        feed=feed_addr,
        fallback_feed=oracle.get("fallback_feed") or registry.zero,
        threshold=threshold,
        comparator=comparator,
        max_stale=max_stale,
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


# ----------------------------------------------------------------- scalar markets


@dataclass
class ScalarCreateMarketArgs:
    question: str
    question_hash: str
    close_at: int
    lower: int
    upper: int
    oracle_params: str  # 0x-encoded scalar oracle params
    market_id: str
    feed: str

    def as_tx_args(self) -> list:
        """Positional args for ScalarMarketEngine.createMarket."""
        return [self.question_hash, self.close_at, self.lower, self.upper, self.oracle_params]


def build_scalar_create_market_args(
    proposal: Dict[str, Any],
    chain_id: int,
    registry: FeedRegistry,
    now_ts: int,
) -> ScalarCreateMarketArgs:
    """Map a scalar proposal to ScalarMarketEngine.createMarket arguments.

    Unlike the binary path, a scalar market carries no committed probability — the
    [lower, upper] band and the oracle define it — so no Cartesi forecast is
    threaded. The marketId derivation is identical (keccak of questionHash, closeAt,
    chainId), so dedupe works the same way.
    """
    question = proposal.get("question")
    close_at = proposal.get("close_at")
    band = proposal.get("band")
    oracle = proposal.get("oracle")
    if not question or close_at is None or not band or not oracle:
        raise SkipProposal("scalar proposal missing question/close_at/band/oracle")

    close_at = _uint64(close_at, "close_at")
    if close_at <= now_ts:
        raise SkipProposal(f"close_at in the past ({close_at} <= {now_ts})")

    lower = _int256(band.get("lower"), "lower")
    upper = _int256(band.get("upper"), "upper")
    if upper <= lower:
        raise SkipProposal(f"band upper must exceed lower ({upper} <= {lower})")

    feed_sym = oracle.get("feed")
    feed_addr = registry.resolve(feed_sym) if feed_sym else None
    if feed_addr is None:
        raise SkipProposal(f"no resolver address for feed {feed_sym!r}")

    target_decimals = _as_int(oracle.get("target_decimals", 0), "target_decimals")
    if not 0 <= target_decimals <= 36:
        raise SkipProposal(f"target_decimals out of range (0..36): {target_decimals}")
    max_stale = _uint64(oracle.get("max_stale", 3600), "max_stale")

    params = abi.encode_scalar_oracle_params(
        feed=feed_addr,
        fallback_feed=oracle.get("fallback_feed") or registry.zero,
        target_decimals=target_decimals,
        max_stale=max_stale,
    )

    qhash = abi.question_hash(question)
    mid = abi.market_id(qhash, close_at, chain_id)

    return ScalarCreateMarketArgs(
        question=question,
        question_hash=qhash,
        close_at=close_at,
        lower=lower,
        upper=upper,
        oracle_params=params,
        market_id=mid,
        feed=feed_addr,
    )


# ------------------------------------------------------------ categorical markets


@dataclass
class CategoricalCreateMarketArgs:
    question: str
    question_hash: str
    close_at: int
    outcome_count: int
    oracle_params: str  # 0x-encoded categorical oracle params
    market_id: str
    feed: str

    def as_tx_args(self) -> list:
        """Positional args for CategoricalMarketEngine.createMarket."""
        return [self.question_hash, self.close_at, self.outcome_count, self.oracle_params]


def _outcome_count(proposal: Dict[str, Any]) -> int:
    """Derive N from an ``outcomes`` label list (preferred) or ``outcome_count``."""
    outcomes = proposal.get("outcomes")
    if outcomes is not None:
        if not isinstance(outcomes, (list, tuple)):
            raise SkipProposal(f"outcomes must be a list, got {type(outcomes).__name__}")
        n = len(outcomes)
    elif proposal.get("outcome_count") is not None:
        n = _as_int(proposal["outcome_count"], "outcome_count")
    else:
        raise SkipProposal("categorical proposal missing outcomes/outcome_count")
    if not 2 <= n <= MAX_OUTCOMES:
        raise SkipProposal(f"outcome_count out of range (2..{MAX_OUTCOMES}): {n}")
    return n


def build_categorical_create_market_args(
    proposal: Dict[str, Any],
    chain_id: int,
    registry: FeedRegistry,
    now_ts: int,
) -> CategoricalCreateMarketArgs:
    """Map a categorical proposal to CategoricalMarketEngine.createMarket arguments.

    Like the scalar path, a categorical market carries no committed probability —
    the outcome set and the oracle define it — so no Cartesi forecast is threaded.
    The marketId derivation is identical (keccak of questionHash, closeAt, chainId),
    so dedupe is cross-consistent with the binary and scalar engines.
    """
    question = proposal.get("question")
    close_at = proposal.get("close_at")
    oracle = proposal.get("oracle")
    if not question or close_at is None or not oracle:
        raise SkipProposal("categorical proposal missing question/close_at/oracle")

    close_at = _uint64(close_at, "close_at")
    if close_at <= now_ts:
        raise SkipProposal(f"close_at in the past ({close_at} <= {now_ts})")

    outcome_count = _outcome_count(proposal)

    feed_sym = oracle.get("feed")
    feed_addr = registry.resolve(feed_sym) if feed_sym else None
    if feed_addr is None:
        raise SkipProposal(f"no resolver address for feed {feed_sym!r}")

    max_stale = _uint64(oracle.get("max_stale", 3600), "max_stale")

    params = abi.encode_categorical_oracle_params(
        feed=feed_addr,
        fallback_feed=oracle.get("fallback_feed") or registry.zero,
        max_stale=max_stale,
    )

    qhash = abi.question_hash(question)
    mid = abi.market_id(qhash, close_at, chain_id)

    return CategoricalCreateMarketArgs(
        question=question,
        question_hash=qhash,
        close_at=close_at,
        outcome_count=outcome_count,
        oracle_params=params,
        market_id=mid,
        feed=feed_addr,
    )
