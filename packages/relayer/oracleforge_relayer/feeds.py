"""Symbolic feed -> on-chain resolver address registry.

The AI generator emits symbolic feed ids ("EUR/USD", "ECON/CPI", "FUNCTIONS/NOAA").
The relayer resolves each to the address the ChainlinkOracleAdapter should read:
  * a Chainlink Data Feed aggregator (price/econ feeds), or
  * a Chainlink Functions consumer that writes a result (GDELT, NOAA, custom).

Addresses below are PLACEHOLDERS — replace with the real Gnosis Chain Chainlink
feed addresses (https://docs.chain.link/data-feeds/price-feeds/addresses?network=gnosis)
and your deployed Functions consumers, or override via the ORACLEFORGE_FEEDS env
(JSON map). Unknown feeds resolve to None and the proposal is skipped, not
submitted with a bogus address.
"""
from __future__ import annotations

import json
import os
from typing import Dict, Optional

_ZERO = "0x0000000000000000000000000000000000000000"

# Placeholder addresses — DO NOT use on mainnet without replacing.
_DEFAULT: Dict[str, str] = {
    "EUR/USD": "0x000000000000000000000000000000000000Fe01",
    "ETH/USD": "0x000000000000000000000000000000000000Fe02",
    "BTC/DVOL": "0x000000000000000000000000000000000000Fe03",
    "ECON/CPI": "0x000000000000000000000000000000000000Fe04",
    "ETH/STAKED_RATIO": "0x000000000000000000000000000000000000Fe05",
    "FUNCTIONS/GDELT": "0x000000000000000000000000000000000000Fe06",
    "FUNCTIONS/NOAA": "0x000000000000000000000000000000000000Fe07",
    # Categorical (N-outcome) data sources — Chainlink Functions consumers that
    # report a winning index (sports result, election seat, award).
    "FUNCTIONS/SPORTS": "0x000000000000000000000000000000000000Fe08",
    "FUNCTIONS/ELECTION": "0x000000000000000000000000000000000000Fe09",
}


def _load_overrides() -> Dict[str, str]:
    raw = os.environ.get("ORACLEFORGE_FEEDS")
    if not raw:
        return {}
    try:
        return {k: str(v) for k, v in json.loads(raw).items()}
    except (ValueError, TypeError):
        return {}


class FeedRegistry:
    def __init__(self, extra: Optional[Dict[str, str]] = None):
        self.map: Dict[str, str] = {**_DEFAULT, **_load_overrides(), **(extra or {})}

    def resolve(self, symbol: str) -> Optional[str]:
        return self.map.get(symbol)

    @property
    def zero(self) -> str:
        return _ZERO
