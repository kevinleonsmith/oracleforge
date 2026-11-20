"""OracleForge Arweave archival worker.

Persists immutable artifacts (market specs, oracle evidence, model outputs,
governance, simulations) to Arweave and writes the resulting tx id back into the
Tableland ``*_arweave_tx`` columns. Content-addressed and deduplicated: the sha256
of the canonical payload is stored as an Arweave tag and alongside the tx id, so
anyone can verify the permanent record against what the chain references.
"""
from .archiver import (Archiver, artifact_from_governance, artifact_from_market,
                       artifact_from_oracle_report, artifact_from_prediction,
                       artifact_from_simulation)
from .models import Artifact, ArtifactKind, Receipt
from .canonical import canonical_bytes, content_hash

__all__ = [
    "Archiver", "Artifact", "ArtifactKind", "Receipt",
    "artifact_from_market", "artifact_from_oracle_report", "artifact_from_prediction",
    "artifact_from_governance", "artifact_from_simulation",
    "canonical_bytes", "content_hash",
]
__version__ = "0.1.0"
