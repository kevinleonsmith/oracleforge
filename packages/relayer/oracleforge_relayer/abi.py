"""Minimal ABI encoding for exactly the shapes the relayer submits.

No eth-abi dependency: the only encodings needed are a static 5-tuple (oracle
params) and a packed concat (marketId preimage), both trivial and fully tested.
"""
from __future__ import annotations

from .keccak import keccak256

_U256 = (1 << 256) - 1


def _addr_word(addr: str) -> bytes:
    a = int(addr, 16) & ((1 << 160) - 1)
    return a.to_bytes(32, "big")


def _uint_word(n: int) -> bytes:
    if n < 0:
        raise ValueError("uint cannot be negative")
    return (n & _U256).to_bytes(32, "big")


def _int_word(n: int) -> bytes:
    # two's complement over 256 bits
    return (n & _U256).to_bytes(32, "big")


def encode_oracle_params(
    feed: str, fallback_feed: str, threshold: int, comparator: int, max_stale: int
) -> str:
    """abi.encode(address,address,int256,uint8,uint64) -> 0x + 160 bytes.

    Matches exactly what ChainlinkOracleAdapter.configure decodes.
    """
    if comparator not in (0, 1):
        raise ValueError("comparator must be 0 or 1")
    body = (
        _addr_word(feed)
        + _addr_word(fallback_feed)
        + _int_word(threshold)
        + _uint_word(comparator)
        + _uint_word(max_stale)
    )
    return "0x" + body.hex()


def question_hash(question: str) -> str:
    """keccak256(utf8(question)) — the on-chain bytes32 questionHash."""
    return "0x" + keccak256(question.encode("utf-8")).hex()


def market_id(question_hash_hex: str, close_at: int, chain_id: int) -> str:
    """keccak256(abi.encodePacked(questionHash, uint64 closeAt, uint256 chainId)).

    Mirrors MarketEngine.createMarket's marketId derivation, so the relayer can
    predict the id a creation will produce (for dedupe / logging).
    """
    qh = bytes.fromhex(question_hash_hex[2:] if question_hash_hex.startswith("0x") else question_hash_hex)
    if len(qh) != 32:
        raise ValueError("questionHash must be 32 bytes")
    packed = qh + close_at.to_bytes(8, "big") + chain_id.to_bytes(32, "big")
    return "0x" + keccak256(packed).hex()
