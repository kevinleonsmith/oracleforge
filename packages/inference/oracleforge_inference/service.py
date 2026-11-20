"""Inference engine — wraps an embedder + drafter behind the request/response API."""
from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger("oracleforge.inference")

# Reuse the Embedder implementations from the AI package (installed in the image;
# resolved from source here).
try:
    from oracleforge_ai.embeddings import Embedder, HashingEmbedder, TransformerEmbedder
except ModuleNotFoundError:  # running from source in the monorepo
    sys.path.insert(
        0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ai-market-generator"))
    )
    from oracleforge_ai.embeddings import Embedder, HashingEmbedder, TransformerEmbedder

from .drafter import Drafter, LLMDrafter, TemplateDrafter
from .schemas import (DraftRequest, DraftResponse, EmbedRequest, EmbedResponse, HealthResponse)


class InferenceEngine:
    def __init__(self, embedder: Embedder, drafter: Drafter, model_name: str, gpu: bool):
        self.embedder = embedder
        self.drafter = drafter
        self.model_name = model_name
        self.gpu = gpu

    def embed(self, req: EmbedRequest) -> EmbedResponse:
        vecs = [self.embedder.embed(t) for t in req.texts]
        return EmbedResponse(model=self.model_name, dim=self.embedder.dim, embeddings=vecs)

    def draft(self, req: DraftRequest) -> DraftResponse:
        q = self.drafter.draft(req.topic, req.signals, req.category)
        return DraftResponse(question=q, model=self.drafter.name)

    def health(self) -> HealthResponse:
        return HealthResponse(
            status="ok", embedder=type(self.embedder).__name__,
            dim=self.embedder.dim, drafter=self.drafter.name, gpu=self.gpu,
        )


def build_engine(
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    device: str = "cuda",
    use_llm: bool = False,
) -> InferenceEngine:
    """Load the real GPU embedder if available, else fall back to the stdlib
    hashing embedder so the service always starts (dev/CI)."""
    try:
        import importlib

        importlib.import_module("sentence_transformers")  # presence check, no download
        embedder: Embedder = TransformerEmbedder(model_name)
        gpu = device == "cuda"
        logger.info("using TransformerEmbedder %s on %s", model_name, device)
    except Exception:  # noqa: BLE001
        embedder = HashingEmbedder()
        gpu = False
        model_name = "hashing-256 (fallback)"
        logger.warning("sentence-transformers unavailable; using HashingEmbedder fallback")

    drafter: Drafter = TemplateDrafter()
    if use_llm:
        try:
            drafter = LLMDrafter(device=device)
        except Exception:  # noqa: BLE001
            logger.warning("LLM drafter unavailable; using TemplateDrafter")

    return InferenceEngine(embedder, drafter, model_name, gpu)
