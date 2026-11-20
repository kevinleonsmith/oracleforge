"""Relayer configuration from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass

# Chain ids
GNOSIS = 100
CHIADO = 10200


@dataclass
class Config:
    rpc_url: str
    chain_id: int
    private_key: str
    engine_address: str
    cartesi_graphql_url: str
    notice_source: str  # "stub" | "graphql"
    dry_run: bool

    @classmethod
    def from_env(cls) -> "Config":
        chain = os.environ.get("NEXT_PUBLIC_CHAIN", "chiado")
        chain_id = GNOSIS if chain == "gnosis" else CHIADO
        return cls(
            rpc_url=os.environ.get("RELAYER_RPC_URL", os.environ.get("CHIADO_RPC_URL", "")),
            chain_id=int(os.environ.get("RELAYER_CHAIN_ID", chain_id)),
            private_key=os.environ.get("RELAYER_PK", ""),
            engine_address=os.environ.get("MARKET_ENGINE_ADDRESS", ""),
            cartesi_graphql_url=os.environ.get(
                "CARTESI_GRAPHQL_URL", "http://localhost:8080/graphql"
            ),
            notice_source=os.environ.get("RELAYER_NOTICE_SOURCE", "stub"),
            dry_run=os.environ.get("RELAYER_DRY_RUN", "").lower() in ("1", "true", "yes"),
        )
