"""Archiver configuration from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Config:
    backend: str          # "local" | "turbo"
    local_store: str
    gateway: str
    wallet_path: str
    tableland_writeback: bool

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            backend=os.environ.get("ARWEAVE_BACKEND", "local"),
            local_store=os.environ.get("ARWEAVE_LOCAL_STORE", "./.arweave-store"),
            gateway=os.environ.get("ARWEAVE_GATEWAY", "https://arweave.net/"),
            wallet_path=os.environ.get("ARWEAVE_WALLET_JSON", ""),
            tableland_writeback=os.environ.get("ARCHIVER_TABLELAND_WRITEBACK", "").lower()
            in ("1", "true", "yes"),
        )
