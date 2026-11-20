"""Embedding interface + a deterministic stdlib fallback.

The pipeline depends only on the ``Embedder`` protocol. In production you swap in
a HuggingFace sentence-transformer (see ``TransformerEmbedder``) without touching
the clustering or generation code. The default ``HashingEmbedder`` is a
deterministic bag-of-hashed-tokens vector — good enough to cluster and dedupe in
CI and inside a Cartesi Machine where pulling a model would break reproducibility.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import List, Protocol

_TOKEN = re.compile(r"[a-z0-9]+")


class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> List[float]: ...


class HashingEmbedder:
    """Deterministic hashing embedder (no external deps, no network).

    Maps tokens into a fixed-dim vector via feature hashing, then L2-normalizes.
    Deterministic across machines -> safe for Cartesi fraud-proof replay.
    """

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        for tok in _TOKEN.findall(text.lower()):
            h = int.from_bytes(hashlib.sha1(tok.encode()).digest()[:8], "big")
            idx = h % self.dim
            sign = 1.0 if (h >> 63) & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class TransformerEmbedder:
    """Production embedder backed by sentence-transformers / HF Transformers.

    Lazily imported so the stdlib core never requires torch. Only used when the
    service runs on Akash GPU nodes, not inside the deterministic Cartesi path.
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None
        self.dim = 384

    def _lazy(self):
        if self._model is None:  # pragma: no cover - requires torch
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
            self.dim = self._model.get_sentence_embedding_dimension()
        return self._model

    def embed(self, text: str) -> List[float]:  # pragma: no cover - requires torch
        return self._lazy().encode(text, normalize_embeddings=True).tolist()


def cosine(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # vectors are L2-normalized
