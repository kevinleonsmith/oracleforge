"""Chain layer — submits the permissionless resolve() poke.

``GnosisResolver`` uses web3 (lazy); ``DryRunResolver`` records calls without a
network. Both also expose the oracle address so the watcher can build a
ChainOracleView against the same node.
"""
from __future__ import annotations

import logging
from typing import Optional, Protocol

logger = logging.getLogger("oracleforge.resolver.chain")

ENGINE_ABI = [
    {
        "type": "function", "name": "resolve", "stateMutability": "nonpayable",
        "inputs": [{"name": "marketId", "type": "bytes32"}], "outputs": [],
    },
    {
        "type": "function", "name": "finalize", "stateMutability": "nonpayable",
        "inputs": [{"name": "marketId", "type": "bytes32"}], "outputs": [],
    },
    {
        "type": "function", "name": "challengeWindow", "stateMutability": "view",
        "inputs": [], "outputs": [{"name": "", "type": "uint64"}],
    },
    {
        "type": "function", "name": "proposedAt", "stateMutability": "view",
        "inputs": [{"name": "", "type": "bytes32"}], "outputs": [{"name": "", "type": "uint64"}],
    },
    {
        "type": "function", "name": "oracle", "stateMutability": "view",
        "inputs": [], "outputs": [{"name": "", "type": "address"}],
    },
    {
        "type": "function", "name": "getMarket", "stateMutability": "view",
        "inputs": [{"name": "marketId", "type": "bytes32"}],
        "outputs": [{
            "name": "", "type": "tuple",
            "components": [
                {"name": "questionHash", "type": "bytes32"},
                {"name": "createdAt", "type": "uint64"},
                {"name": "closeAt", "type": "uint64"},
                {"name": "aiProbBps", "type": "uint16"},
                {"name": "status", "type": "uint8"},
                {"name": "outcome", "type": "uint8"},
                {"name": "yesPool", "type": "uint256"},
                {"name": "noPool", "type": "uint256"},
            ],
        }],
    },
]


class Resolver(Protocol):
    chain_id: int

    def resolve(self, market_id: str) -> str: ...
    def finalize(self, market_id: str) -> str: ...
    def market_status(self, market_id: str) -> int: ...


class GnosisResolver:
    def __init__(self, rpc_url: str, engine_address: str, chain_id: int,
                 private_key: Optional[str] = None):
        from web3 import Web3  # lazy

        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.chain_id = chain_id
        self.engine = self.w3.eth.contract(
            address=Web3.to_checksum_address(engine_address), abi=ENGINE_ABI
        )
        self.acct = self.w3.eth.account.from_key(private_key) if private_key else None
        self.account = self.acct.address if self.acct else None

    def oracle_address(self) -> str:
        return self.engine.functions.oracle().call()

    def market_status(self, market_id: str) -> int:
        return int(self.engine.functions.getMarket(market_id).call()[4])

    def challenge_window(self) -> int:
        """Global challenge window (seconds); 0 means instant finalization."""
        return int(self.engine.functions.challengeWindow().call())

    def proposed_at(self, market_id: str) -> int:
        return int(self.engine.functions.proposedAt(market_id).call())

    def _send(self, fn, label: str) -> str:
        if self.acct is None:
            raise RuntimeError(f"{label}() needs a signer; set RESOLVER_PK")
        tx = fn.build_transaction({
            "from": self.account,
            "nonce": self.w3.eth.get_transaction_count(self.account),
            "chainId": self.chain_id,
        })
        signed = self.acct.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status != 1:
            raise RuntimeError(f"{label} reverted: {tx_hash.hex()}")
        return tx_hash.hex()

    def resolve(self, market_id: str) -> str:
        return self._send(self.engine.functions.resolve(market_id), "resolve")

    def finalize(self, market_id: str) -> str:
        return self._send(self.engine.functions.finalize(market_id), "finalize")


class DryRunResolver:
    def __init__(self, chain_id: int = 10200):
        self.chain_id = chain_id
        self.resolved: list[str] = []   # markets a resolve() poke was sent for
        self.finalized: list[str] = []  # markets a finalize() poke was sent for

    def market_status(self, market_id: str) -> int:
        from .models import Status

        if market_id in self.finalized:
            return int(Status.Resolved)
        if market_id in self.resolved:
            return int(Status.Closed)  # proposed, awaiting finalization
        return int(Status.Open)

    def resolve(self, market_id: str) -> str:
        self.resolved.append(market_id)
        logger.info("[dry-run] resolve(%s)", market_id)
        return "0xDRYRUN" + market_id[2:10]

    def finalize(self, market_id: str) -> str:
        self.finalized.append(market_id)
        logger.info("[dry-run] finalize(%s)", market_id)
        return "0xFINAL0" + market_id[2:10]
