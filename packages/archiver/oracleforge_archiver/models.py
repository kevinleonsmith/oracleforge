"""Artifact + receipt types for the archival worker."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ArtifactKind(str, Enum):
    MARKET = "market"               # full question text + creation spec + evidence
    ORACLE_REPORT = "oracle-report"  # settlement evidence
    PREDICTION = "prediction"        # AI model output
    GOVERNANCE = "governance"        # proposal text + discussion
    SIMULATION = "simulation"        # scenario / Monte Carlo payload
    DISPUTE = "dispute"              # dispute record


@dataclass
class Artifact:
    """Something to persist permanently, plus where its tx id gets written back."""

    kind: ArtifactKind
    payload: Dict[str, Any]
    # Tableland write-back target (which row's arweave_tx column to set).
    table: str
    id_column: str
    row_id: str
    tx_column: str = "arweave_tx"
    extra_tags: Dict[str, str] = field(default_factory=dict)


@dataclass
class Receipt:
    content_hash: str
    tx_id: str
    url: str
    size: int
    kind: str
    deduped: bool = False
    written_back: bool = False
    tags: List[Dict[str, str]] = field(default_factory=list)
