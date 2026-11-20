"""Confidence scoring.

Confidence decomposes per source and aggregates into a single score in [0,1].
Each source contributes its reliability weight scaled by corroboration (how many
independent signals in the cluster support the topic) and recency.
"""
from __future__ import annotations

import math
from typing import Dict, List

from .models import Signal


def score_sources(signals: List[Signal], now_ts: int = 1737010000) -> Dict[str, float]:
    """Per-source confidence from reliability, corroboration and recency."""
    by_source: Dict[str, List[Signal]] = {}
    for s in signals:
        by_source.setdefault(s.source, []).append(s)

    scores: Dict[str, float] = {}
    for source, sigs in by_source.items():
        reliability = sum(s.weight for s in sigs) / len(sigs)
        # corroboration: diminishing returns on count
        corrob = 1.0 - math.exp(-0.6 * len(sigs))
        # recency: newest signal in the group, decays over ~10 days
        newest = max(s.ts for s in sigs)
        age_days = max(0.0, (now_ts - newest) / 86400.0)
        recency = math.exp(-age_days / 10.0)
        scores[source] = round(reliability * (0.5 + 0.3 * corrob + 0.2 * recency), 4)
    return scores


def aggregate(scores: Dict[str, float]) -> float:
    """Blend per-source scores into one confidence value in [0,1]."""
    if not scores:
        return 0.0
    vals = list(scores.values())
    # weight the strongest source a bit more than a flat mean
    vals.sort(reverse=True)
    weights = [1.0 / (i + 1) for i in range(len(vals))]
    wsum = sum(weights)
    return round(sum(v * w for v, w in zip(vals, weights)) / wsum, 4)
