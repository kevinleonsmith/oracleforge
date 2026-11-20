"""The market-generation pipeline.

    signals -> cluster -> draft question -> dedupe -> confidence -> forecast -> proposal

Each cluster of corroborating signals becomes at most one market. The question is
drafted from a per-category template (a real deployment swaps this for an LLM call
behind the same interface), deduplicated against open markets, scored for
confidence, and assigned an initial YES probability by the deterministic Cartesi
forecaster.
"""
from __future__ import annotations

from typing import List, Optional

from . import confidence
from .cartesi import CartesiRunner
from .clustering import Cluster, cluster_signals, is_duplicate
from .embeddings import Embedder, HashingEmbedder
from .models import MarketProposal, OracleSpec, Signal
from .signals import SignalSource, default_sources

# Category -> (question template, oracle spec factory, horizon in days).
# A production system drafts the question with an LLM; the oracle spec is chosen
# by matching the topic to an available Chainlink feed.
_CATEGORY_RULES = {
    "us-rates": {
        "category": "MACRO",
        "template": "Will US CPI print below 2.6% YoY for the next release?",
        "oracle": lambda: OracleSpec(feed="ECON/CPI", threshold=260, comparator=1),
        "horizon_days": 45,
    },
    "eu-fx": {
        "category": "MACRO",
        "template": "Will EUR/USD close at or above 1.10 at market settlement?",
        "oracle": lambda: OracleSpec(feed="EUR/USD", threshold=110_000_000, comparator=0),
        "horizon_days": 30,
    },
    "geopolitics": {
        "category": "GEO",
        "template": "Will a ceasefire in the Eastern corridor hold through the settlement date?",
        "oracle": lambda: OracleSpec(feed="FUNCTIONS/GDELT", threshold=1, comparator=0),
        "horizon_days": 60,
    },
    "eth-staking": {
        "category": "CRYPTO",
        "template": "Will the ETH staking ratio exceed 32% before settlement?",
        "oracle": lambda: OracleSpec(feed="ETH/STAKED_RATIO", threshold=3_200, comparator=0),
        "horizon_days": 90,
    },
    "volatility": {
        "category": "CRYPTO",
        "template": "Will BTC 30d implied volatility exceed 55 at settlement?",
        "oracle": lambda: OracleSpec(feed="BTC/DVOL", threshold=5_500, comparator=0),
        "horizon_days": 21,
    },
    "hurricane": {
        "category": "CLIMATE",
        "template": "Will the Atlantic season record at least 4 Category-5 hurricanes?",
        "oracle": lambda: OracleSpec(feed="FUNCTIONS/NOAA", threshold=4, comparator=0),
        "horizon_days": 120,
    },
}


class MarketGenerator:
    def __init__(
        self,
        embedder: Optional[Embedder] = None,
        runner: Optional[CartesiRunner] = None,
        cluster_threshold: float = 0.5,
        min_confidence: float = 0.45,
    ):
        self.embedder = embedder or HashingEmbedder()
        self.runner = runner or CartesiRunner()
        self.cluster_threshold = cluster_threshold
        self.min_confidence = min_confidence

    def gather(self, sources: Optional[List[SignalSource]] = None) -> List[Signal]:
        sources = sources or default_sources()
        out: List[Signal] = []
        for s in sources:
            out.extend(s.fetch())
        return out

    def _topic_of(self, cluster: Cluster) -> str:
        # most common topic label in the cluster
        topics = [s.topic for s in cluster.signals]
        return max(set(topics), key=topics.count)

    def _signal_prior(self, cluster: Cluster) -> float:
        """Directional prior in [-1,1] from signal weights (sign heuristic).

        MVP: treat corroborated, high-weight clusters as leaning YES. A real
        system derives direction from stance classification per signal.
        """
        avg_w = sum(s.weight for s in cluster.signals) / len(cluster.signals)
        return max(-1.0, min(1.0, (avg_w - 0.5) * 2.0))

    def propose(
        self,
        signals: Optional[List[Signal]] = None,
        open_questions: Optional[List[str]] = None,
        now_ts: int = 1737010000,
    ) -> List[MarketProposal]:
        signals = signals if signals is not None else self.gather()
        open_questions = open_questions or []

        clusters = cluster_signals(signals, self.embedder, self.cluster_threshold)
        proposals: List[MarketProposal] = []

        for cluster in clusters:
            topic = self._topic_of(cluster)
            rule = _CATEGORY_RULES.get(topic)
            if rule is None:
                continue  # no resolvable template/feed for this topic yet

            question = rule["template"]

            # duplicate-market prevention across open markets and this batch
            seen = open_questions + [p.question for p in proposals]
            if is_duplicate(question, seen, self.embedder):
                continue

            scores = confidence.score_sources(cluster.signals, now_ts=now_ts)
            conf = confidence.aggregate(scores)
            if conf < self.min_confidence:
                continue

            prior = self._signal_prior(cluster)
            priors = [prior]
            forecast = self.runner.forecast(question, priors, base_rate=0.5)

            proposals.append(
                MarketProposal(
                    question=question,
                    category=rule["category"],
                    close_at=now_ts + rule["horizon_days"] * 86400,
                    ai_prob_bps=forecast.prob_bps,
                    confidence=conf,
                    confidence_by_source=scores,
                    oracle=rule["oracle"](),
                    evidence=[s.text for s in cluster.signals],
                    cluster_id=cluster.id,
                    priors=priors,
                )
            )

        # highest-confidence first
        proposals.sort(key=lambda p: p.confidence, reverse=True)
        return proposals
