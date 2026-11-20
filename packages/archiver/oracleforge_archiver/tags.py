"""Arweave tag construction.

Tags make artifacts queryable on the Arweave permaweb (via GraphQL gateways) and
carry the integrity hash. Keep names stable — they are the index.
"""
from __future__ import annotations

import time
from typing import Dict, List

from .models import Artifact

APP_NAME = "OracleForge"
APP_VERSION = "0.1.0"


def build_tags(artifact: Artifact, content_hash: str, now: int | None = None) -> List[Dict[str, str]]:
    ts = int(time.time()) if now is None else now
    tags = [
        {"name": "App-Name", "value": APP_NAME},
        {"name": "App-Version", "value": APP_VERSION},
        {"name": "Content-Type", "value": "application/json"},
        {"name": "Type", "value": artifact.kind.value},
        {"name": "Content-SHA256", "value": content_hash},
        {"name": "Unix-Time", "value": str(ts)},
        # retrieval cross-reference to the relational row
        {"name": "Table", "value": artifact.table},
        {"name": "Row-Id", "value": str(artifact.row_id)},
    ]
    for k, v in artifact.extra_tags.items():
        tags.append({"name": k, "value": str(v)})
    return tags
