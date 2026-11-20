"""OracleForge AI market generator.

Pipeline that ingests real-world signals, clusters them semantically, proposes
binary prediction markets, scores confidence per source, and initializes a YES
probability via a deterministic forecast.

The *core* runs on the Python standard library alone so it executes inside a
Cartesi Machine Linux rootfs (and in CI) with no heavy dependencies. Production
embedders / LLMs (HuggingFace Transformers, LangChain) plug in behind the
``Embedder`` interface in ``embeddings.py`` without changing the pipeline.
"""

from .models import Signal, MarketProposal, OracleSpec
from .generator import MarketGenerator

__all__ = ["Signal", "MarketProposal", "OracleSpec", "MarketGenerator"]
__version__ = "0.1.0"
