"""Oracle view — "can this market resolve yet, and to what?".

``StubOracleView`` is a fixed map for dev/tests. ``ChainOracleView`` calls the
ChainlinkOracleAdapter's ``resolve(marketId)`` view (deterministic, side-effect
free) to decide readiness without sending a transaction.
"""
from __future__ import annotations

from typing import Dict, Protocol

from .models import Outcome

ORACLE_ABI = [
    {
        "type": "function", "name": "resolve", "stateMutability": "view",
        "inputs": [{"name": "marketId", "type": "bytes32"}],
        "outputs": [{"name": "", "type": "uint8"}],
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
