"""Oracle view — "can this market resolve yet, and to what?".

``StubOracleView`` is a fixed map for dev/tests. ``ChainOracleView`` calls the
ChainlinkOracleAdapter's ``resolve(marketId)`` view (deterministic, side-effect
free) to decide readiness without sending a transaction.

The scalar variants (``*ScalarOracleView``) call the ScalarChainlinkAdapter's
``latestValue(marketId)`` view instead, which reports ``(ready, value)`` rather
than a yes/no outcome.
"""
from __future__ import annotations

from typing import Dict, Protocol, Tuple

from .models import Outcome

ORACLE_ABI = [
    {
        "type": "function", "name": "resolve", "stateMutability": "view",
        "inputs": [{"name": "marketId", "type": "bytes32"}],
        "outputs": [{"name": "", "type": "uint8"}],
    }
]

SCALAR_ORACLE_ABI = [
    {
        "type": "function", "name": "latestValue", "stateMutability": "view",
        "inputs": [{"name": "marketId", "type": "bytes32"}],
        "outputs": [{"name": "ready", "type": "bool"}, {"name": "value", "type": "int256"}],
    }
]

CATEGORICAL_ORACLE_ABI = [
    {
        "type": "function", "name": "latestOutcome", "stateMutability": "view",
        "inputs": [{"name": "marketId", "type": "bytes32"}],
        "outputs": [{"name": "ready", "type": "bool"}, {"name": "outcome", "type": "uint8"}],
    }
]


class OracleView(Protocol):
    def outcome(self, market_id: str) -> Outcome: ...


class StubOracleView:
    def __init__(self, outcomes: Dict[str, Outcome], default: Outcome = Outcome.Pending):
        self._outcomes = outcomes
        self._default = default

    def outcome(self, market_id: str) -> Outcome:
        return self._outcomes.get(market_id, self._default)


class ChainOracleView:
    def __init__(self, w3, oracle_address: str):
        self.contract = w3.eth.contract(
            address=w3.to_checksum_address(oracle_address), abi=ORACLE_ABI
        )

    def outcome(self, market_id: str) -> Outcome:
        return Outcome(int(self.contract.functions.resolve(market_id).call()))


# --------------------------------------------------------------- scalar markets


class ScalarOracleView(Protocol):
    def value(self, market_id: str) -> Tuple[bool, int]: ...


class StubScalarOracleView:
    """Fixed map market_id -> (ready, value) for dev/tests."""

    def __init__(self, values: Dict[str, Tuple[bool, int]]):
        self._values = values

    def value(self, market_id: str) -> Tuple[bool, int]:
        return self._values.get(market_id, (False, 0))


class ChainScalarOracleView:
    def __init__(self, w3, oracle_address: str):
        self.contract = w3.eth.contract(
            address=w3.to_checksum_address(oracle_address), abi=SCALAR_ORACLE_ABI
        )

    def value(self, market_id: str) -> Tuple[bool, int]:
        ready, v = self.contract.functions.latestValue(market_id).call()
        return bool(ready), int(v)


# ----------------------------------------------------------- categorical markets


class CategoricalOracleView(Protocol):
    def winning_outcome(self, market_id: str) -> Tuple[bool, int]: ...


class StubCategoricalOracleView:
    """Fixed map market_id -> (ready, winning outcome index) for dev/tests.

    An outcome of ``INVALID_OUTCOME`` (0xFF, the engine's out-of-range sentinel)
    signals a void/cancelled market.
    """

    def __init__(self, outcomes: Dict[str, Tuple[bool, int]]):
        self._outcomes = outcomes

    def winning_outcome(self, market_id: str) -> Tuple[bool, int]:
        return self._outcomes.get(market_id, (False, 0))


class ChainCategoricalOracleView:
    def __init__(self, w3, oracle_address: str):
        self.contract = w3.eth.contract(
            address=w3.to_checksum_address(oracle_address), abi=CATEGORICAL_ORACLE_ABI
        )

    def winning_outcome(self, market_id: str) -> Tuple[bool, int]:
        ready, o = self.contract.functions.latestOutcome(market_id).call()
        return bool(ready), int(o)
