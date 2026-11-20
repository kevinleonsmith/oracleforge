"""Canonical serialization + content hashing.

Every artifact is serialized the same way regardless of dict insertion order, so
its content hash is stable and verifiable: anyone who fetches the data from
Arweave can recompute this hash and confirm it matches what was recorded on-chain
(the hash is also stored as an Arweave tag and alongside the tx id in Tableland).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_bytes(obj: Any) -> bytes:
    """Deterministic JSON encoding: sorted keys, no insignificant whitespace."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def content_hash(obj: Any) -> str:
    """0x-prefixed sha256 of the canonical encoding."""
    return "0x" + hashlib.sha256(canonical_bytes(obj)).hexdigest()
