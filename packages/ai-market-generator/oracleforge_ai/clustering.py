"""Semantic clustering + duplicate-market prevention.

Greedy single-pass agglomeration on cosine similarity (deterministic, O(n·k)).
For MVP volumes this is sufficient; swap for HDBSCAN on GPU nodes at scale.
"""
from __future__ import annotations

from typing import List

from .embeddings import Embedder, cosine
from .models import Signal


class Cluster:
    def __init__(self, cluster_id: int, centroid: List[float], signal: Signal):
        self.id = cluster_id
        self.centroid = centroid
        self.signals: List[Signal] = [signal]

    def add(self, vec: List[float], signal: Signal) -> None:
        n = len(self.signals)
        # incremental centroid mean (not re-normalized; cosine tolerates it)
        self.centroid = [(c * n + v) / (n + 1) for c, v in zip(self.centroid, vec)]
        self.signals.append(signal)


def cluster_signals(
    signals: List[Signal], embedder: Embedder, threshold: float = 0.55
) -> List[Cluster]:
    """Group semantically similar signals into topic clusters."""
    clusters: List[Cluster] = []
    for s in signals:
        vec = embedder.embed(s.topic + " " + s.text)
        best, best_sim = None, threshold
        for c in clusters:
            sim = cosine(vec, c.centroid)
            if sim >= best_sim:
                best, best_sim = c, sim
        if best is None:
            clusters.append(Cluster(len(clusters), vec, s))
        else:
            best.add(vec, s)
    return clusters


def is_duplicate(
    question: str,
    existing_questions: List[str],
    embedder: Embedder,
    threshold: float = 0.82,
) -> bool:
    """True if `question` is semantically near an already-open market."""
    qv = embedder.embed(question)
    for eq in existing_questions:
        if cosine(qv, embedder.embed(eq)) >= threshold:
            return True
    return False
