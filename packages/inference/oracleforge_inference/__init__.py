"""OracleForge inference service (Akash GPU path).

The non-deterministic compute path: HuggingFace embeddings + LLM question drafting
that feed market generation. Deployed to Akash via deploy/deploy.yaml. Output here
only *suggests* markets; committed on-chain values come from the deterministic
Cartesi path, so running this on commodity GPUs is safe.
"""
from .service import InferenceEngine, build_engine
from .client import RemoteEmbedder, RemoteDrafter

__all__ = ["InferenceEngine", "build_engine", "RemoteEmbedder", "RemoteDrafter"]
__version__ = "0.1.0"
