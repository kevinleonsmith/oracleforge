"""Signal sources.

A ``SignalSource`` yields ``Signal`` objects. Production sources wrap news APIs,
macro data providers, Chainlink feeds, on-chain indexers, etc. The ``MockSource``
set gives the pipeline deterministic input for tests and local runs.
"""
from __future__ import annotations

from typing import List, Protocol

from .models import Signal


class SignalSource(Protocol):
    name: str

    def fetch(self) -> List[Signal]: ...


class MockMacroSource:
    name = "macro"

    def fetch(self) -> List[Signal]:
        return [
            Signal("macro", "us-rates", "Fed officials signal a possible 50bps cut amid cooling CPI", 0.9, 1737000000),
            Signal("macro", "us-rates", "December CPI prints at 2.6% YoY, below consensus", 0.85, 1737001000),
            Signal("macro", "eu-fx", "ECB holds rates; EUR/USD drifts toward 1.10 support", 0.8, 1737002000),
        ]


class MockNewsSource:
    name = "news"

    def fetch(self) -> List[Signal]:
        return [
            Signal("news", "geopolitics", "Diplomats report progress toward an Eastern-corridor ceasefire", 0.6, 1737003000),
            Signal("news", "geopolitics", "Ceasefire talks resume after weekend escalation", 0.55, 1737004000),
        ]


class MockCryptoSource:
    name = "crypto"

    def fetch(self) -> List[Signal]:
        return [
            Signal("crypto", "eth-staking", "ETH staking ratio approaches 30% as validators queue grows", 0.75, 1737005000),
            Signal("crypto", "volatility", "BTC 30d implied volatility spikes to 48 ahead of options expiry", 0.7, 1737006000),
        ]


class MockClimateSource:
    name = "climate"

    def fetch(self) -> List[Signal]:
        return [
            Signal("climate", "hurricane", "NOAA raises Atlantic season outlook; warm SSTs persist", 0.65, 1737007000),
        ]


def default_sources() -> List[SignalSource]:
    return [MockMacroSource(), MockNewsSource(), MockCryptoSource(), MockClimateSource()]
