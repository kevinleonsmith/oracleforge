"""Inference service configuration from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Config:
    model: str
    device: str
    host: str
    port: int
    use_llm: bool

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            model=os.environ.get("OF_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
            device=os.environ.get("OF_DEVICE", "cuda"),
            host=os.environ.get("OF_HOST", "0.0.0.0"),
            port=int(os.environ.get("OF_PORT", "8070")),
            use_llm=os.environ.get("OF_USE_LLM", "").lower() in ("1", "true", "yes"),
        )
