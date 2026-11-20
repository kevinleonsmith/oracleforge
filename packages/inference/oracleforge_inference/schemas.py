"""Request/response shapes for the inference service (pure, JSON-friendly).

This is the *non-deterministic* GPU path: embeddings and LLM question drafting
that feed market generation upstream. It never produces committed on-chain state —
that is the Cartesi deterministic path's job — so running it on commodity GPUs
(Akash) is safe.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class EmbedRequest:
    texts: List[str]
    normalize: bool = True

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "EmbedRequest":
        texts = d.get("texts")
        if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
            raise ValueError("`texts` must be a list of strings")
        return EmbedRequest(texts=texts, normalize=bool(d.get("normalize", True)))


@dataclass
class EmbedResponse:
    model: str
    dim: int
    embeddings: List[List[float]]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DraftRequest:
    topic: str
    signals: List[str] = field(default_factory=list)
    category: str = ""

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "DraftRequest":
        topic = d.get("topic")
        if not isinstance(topic, str) or not topic:
            raise ValueError("`topic` is required")
        return DraftRequest(
            topic=topic,
            signals=[str(s) for s in d.get("signals", [])],
            category=str(d.get("category", "")),
        )


@dataclass
class DraftResponse:
    question: str
    model: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HealthResponse:
    status: str
    embedder: str
    dim: int
    drafter: str
    gpu: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
