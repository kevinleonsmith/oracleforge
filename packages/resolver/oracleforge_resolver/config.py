"""Resolution-watcher configuration from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass

GNOSIS = 100
CHIADO = 10200


@dataclass
class Config:
    rpc_url: str
    chain_id: int
    private_key: str
    engine_address: str
    oracle_address: str  # optional override; else read from engine.oracle()
    tableland_gateway: str
    markets_table: str
    reports_table: str
    interval: float

    @classmethod
    def from_env(cls) -> "Config":
        chain = os.environ.get("NEXT_PUBLIC_CHAIN", "chiado")
        chain_id = GNOSIS if chain == "gnosis" else CHIADO
        return cls(
            rpc_url=os.environ.get("RESOLVER_RPC_URL", os.environ.get("CHIADO_RPC_URL", "")),
            chain_id=int(os.environ.get("RESOLVER_CHAIN_ID", chain_id)),
            private_key=os.environ.get("RESOLVER_PK", ""),
            engine_address=os.environ.get("MARKET_ENGINE_ADDRESS", ""),
            oracle_address=os.environ.get("ORACLE_ADAPTER_ADDRESS", ""),
            tableland_gateway=os.environ.get(
                "NEXT_PUBLIC_TABLELAND_GATEWAY", "https://tableland.network"
            ),
            markets_table=os.environ.get("MARKETS_TABLE", "markets"),
            reports_table=os.environ.get("ORACLE_REPORTS_TABLE", "oracle_reports"),
            interval=float(os.environ.get("RESOLVER_INTERVAL", "30")),
        )
