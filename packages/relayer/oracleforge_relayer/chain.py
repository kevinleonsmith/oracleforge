"""Gnosis Chain submission layer.

``GnosisChain`` uses web3.py (lazy-imported) to read ``isRelayer`` / market state
and submit ``createMarket``. ``DryRunChain`` implements the same interface with no
network, so the pipeline runs end-to-end locally and in CI.
"""
from __future__ import annotations

import logging
from typing import Protocol

from .mapping import CreateMarketArgs

logger = logging.getLogger("oracleforge.relayer.chain")

# Minimal ABI the relayer needs from MarketEngine.
ENGINE_ABI = [
    {
        "type": "function", "name": "createMarket", "stateMutability": "nonpayable",
        "inputs": [
            {"name": "questionHash", "type": "bytes32"},
            {"name": "closeAt", "type": "uint64"},
            {"name": "aiProbBps", "type": "uint16"},
            {"name": "oracleParams", "type": "bytes"},
        ],
        "outputs": [{"name": "marketId", "type": "bytes32"}],
    },
    {
        "type": "function", "name": "isRelayer", "stateMutability": "view",
        "inputs": [{"name": "", "type": "address"}],
        "outputs": [{"name": "", "type": "bool"}],
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


class Chain(Protocol):
    chain_id: int
    account: str

    def is_relayer(self) -> bool: ...
    def market_exists(self, market_id: str) -> bool: ...
    def create_market(self, args: CreateMarketArgs) -> str: ...


class GnosisChain:
    def __init__(self, rpc_url: str, private_key: str, engine_address: str, chain_id: int):
        from web3 import Web3  # lazy: live path only

        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.acct = self.w3.eth.account.from_key(private_key)
        self.account = self.acct.address
        self.chain_id = chain_id
        self.engine = self.w3.eth.contract(
            address=Web3.to_checksum_address(engine_address), abi=ENGINE_ABI
        )

    def is_relayer(self) -> bool:
        return bool(self.engine.functions.isRelayer(self.account).call())

    def market_exists(self, market_id: str) -> bool:
        m = self.engine.functions.getMarket(market_id).call()
        return int(m[1]) != 0  # createdAt != 0

    def create_market(self, args: CreateMarketArgs) -> str:
        fn = self.engine.functions.createMarket(
            bytes.fromhex(args.question_hash[2:]),
            args.close_at,
            args.ai_prob_bps,
            bytes.fromhex(args.oracle_params[2:]),
        )
        tx = fn.build_transaction({
            "from": self.account,
            "nonce": self.w3.eth.get_transaction_count(self.account),
            "chainId": self.chain_id,
        })
        signed = self.acct.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
        if receipt.status != 1:
            raise RuntimeError(f"createMarket reverted: {tx_hash.hex()}")
        return tx_hash.hex()


class DryRunChain:
    """No-network stand-in; records what would be submitted."""

    def __init__(self, chain_id: int = 10200, account: str = "0xRELAYER"):
        self.chain_id = chain_id
        self.account = account
        self.submitted: list[CreateMarketArgs] = []
        self._existing: set[str] = set()

    def is_relayer(self) -> bool:
        return True

    def market_exists(self, market_id: str) -> bool:
        return market_id in self._existing

    def create_market(self, args: CreateMarketArgs) -> str:
        self.submitted.append(args)
        self._existing.add(args.market_id)
        logger.info("[dry-run] createMarket %s (prob %d bps)", args.market_id, args.ai_prob_bps)
        return "0xDRYRUN" + args.market_id[2:10]
