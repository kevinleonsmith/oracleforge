"""Relayer orchestration.

    proposals ──▶ Cartesi forecast (committed notice) ──▶ createMarket(Gnosis)

For each AI proposal: obtain the committed forecast notice (stub or GraphQL),
map it to createMarket arguments, skip anything already on-chain, and submit.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .chain import Chain
from .feeds import FeedRegistry
from .index import LogMarketIndexSink, MarketIndexRow, MarketIndexSink, PredictionIndexRow
from .mapping import (
    SkipProposal,
    build_categorical_create_market_args,
    build_create_market_args,
    build_scalar_create_market_args,
)
from .notices import StubNoticeSource

logger = logging.getLogger("oracleforge.relayer")

DEFAULT_SAMPLES = 50_000
DEFAULT_BASE_RATE = 0.5


@dataclass
class RelayResult:
    question: str
    market_id: Optional[str]
    status: str  # "submitted" | "exists" | "skipped" | "error"
    detail: str = ""
    tx_hash: Optional[str] = None
    ai_prob_bps: Optional[int] = None


def proposal_to_request(proposal: Dict[str, Any]) -> Dict[str, Any]:
    """Build the Cartesi forecast request that reproduces this proposal's prob."""
    return {
        "op": "forecast",
        "question": proposal["question"],
        "priors": proposal.get("priors", [0.0]),
        "base_rate": DEFAULT_BASE_RATE,
        "samples": DEFAULT_SAMPLES,
    }


class Relayer:
    def __init__(
        self,
        chain: Chain,
        registry: Optional[FeedRegistry] = None,
        notice_source=None,
        graphql_reader=None,
        now_ts_fn=None,
        index_sink: Optional[MarketIndexSink] = None,
    ):
        self.chain = chain
        self.registry = registry or FeedRegistry()
        self.notice_source = notice_source or StubNoticeSource()
        self.graphql_reader = graphql_reader  # set when notice_source is graphql
        # Collects a `markets` index row for each freshly-created market (the
        # catalog the frontend reads). Default logs/collects; swap for a signed sink.
        self.index_sink: MarketIndexSink = index_sink or LogMarketIndexSink()
        import time

        self._now = now_ts_fn or (lambda: int(time.time()))

    def _committed_forecast(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Return the committed forecast notice payload for a request."""
        if getattr(self.notice_source, "name", "stub") == "stub":
            return self.notice_source.forecast(request)
        # GraphQL path: send the input on-chain, then read the notice it produced.
        if self.graphql_reader is None:
            raise RuntimeError("graphql notice source requires a graphql_reader")
        input_index = self.chain.send_cartesi_input(request)  # type: ignore[attr-defined]
        notice = self.graphql_reader.wait_for_forecast(input_index)
        if notice is None:
            raise TimeoutError(f"no forecast notice for input {input_index}")
        return notice

    def relay_one(self, proposal: Dict[str, Any]) -> RelayResult:
        q = proposal.get("question", "<unknown>")
        try:
            request = proposal_to_request(proposal)
            notice = self._committed_forecast(request)
            committed_bps = int(notice["prob_bps"])

            # sanity: committed value should match the generator's local prob
            local_bps = proposal.get("ai_prob_bps")
            if local_bps is not None and local_bps != committed_bps:
                logger.warning(
                    "committed prob %d bps != local %d bps for %r",
                    committed_bps, local_bps, q,
                )

            args = build_create_market_args(
                proposal, committed_bps, self.chain.chain_id, self.registry, self._now()
            )
        except SkipProposal as e:
            return RelayResult(q, None, "skipped", str(e))
        except Exception as e:  # noqa: BLE001
            return RelayResult(q, None, "error", f"{type(e).__name__}: {e}")

        if self.chain.market_exists(args.market_id):
            return RelayResult(q, args.market_id, "exists", "already on-chain",
                               ai_prob_bps=args.ai_prob_bps)
        try:
            tx = self.chain.create_market(args)
        except Exception as e:  # noqa: BLE001
            return RelayResult(q, args.market_id, "error", f"{type(e).__name__}: {e}",
                               ai_prob_bps=args.ai_prob_bps)
        now = self._now()
        self.index_sink.record(MarketIndexRow.from_binary(
            args, category=proposal.get("category", ""), created_at=now))
        # A binary market carries an AI forecast; index it as a predictions row too.
        record_prediction = getattr(self.index_sink, "record_prediction", None)
        if record_prediction is not None:
            record_prediction(PredictionIndexRow.from_notice(args.market_id, notice, now))
        return RelayResult(q, args.market_id, "submitted", "", tx_hash=tx,
                           ai_prob_bps=args.ai_prob_bps)

    def run(self, proposals: List[Dict[str, Any]]) -> List[RelayResult]:
        if not self.chain.is_relayer():
            raise PermissionError(
                f"account {self.chain.account} is not an authorized relayer on the engine"
            )
        results = [self.relay_one(p) for p in proposals]
        counts: Dict[str, int] = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        logger.info("relay complete: %s", counts)
        return results

    # ------------------------------------------------------------ scalar markets

    def relay_scalar_one(self, proposal: Dict[str, Any]) -> RelayResult:
        """Relay one scalar (range) proposal. No Cartesi forecast is needed — the
        band and oracle define the market — so this is a straight map -> create."""
        q = proposal.get("question", "<unknown>")
        try:
            args = build_scalar_create_market_args(
                proposal, self.chain.chain_id, self.registry, self._now()
            )
        except SkipProposal as e:
            return RelayResult(q, None, "skipped", str(e))
        except Exception as e:  # noqa: BLE001
            return RelayResult(q, None, "error", f"{type(e).__name__}: {e}")

        if self.chain.market_exists(args.market_id):
            return RelayResult(q, args.market_id, "exists", "already on-chain")
        try:
            tx = self.chain.create_scalar_market(args)  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001
            return RelayResult(q, args.market_id, "error", f"{type(e).__name__}: {e}")
        self.index_sink.record(MarketIndexRow.from_scalar(
            args, category=proposal.get("category", ""),
            unit=(proposal.get("band") or {}).get("unit", ""), created_at=self._now()))
        return RelayResult(q, args.market_id, "submitted", "", tx_hash=tx)

    def run_scalar(self, proposals: List[Dict[str, Any]]) -> List[RelayResult]:
        if not self.chain.is_relayer():
            raise PermissionError(
                f"account {self.chain.account} is not an authorized relayer on the engine"
            )
        results = [self.relay_scalar_one(p) for p in proposals]
        counts: Dict[str, int] = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        logger.info("scalar relay complete: %s", counts)
        return results

    # ------------------------------------------------------- categorical markets

    def relay_categorical_one(self, proposal: Dict[str, Any]) -> RelayResult:
        """Relay one categorical (N-outcome) proposal. Like scalar, no Cartesi
        forecast is needed — the outcome set and oracle define the market — so this
        is a straight map -> create."""
        q = proposal.get("question", "<unknown>")
        try:
            args = build_categorical_create_market_args(
                proposal, self.chain.chain_id, self.registry, self._now()
            )
        except SkipProposal as e:
            return RelayResult(q, None, "skipped", str(e))
        except Exception as e:  # noqa: BLE001
            return RelayResult(q, None, "error", f"{type(e).__name__}: {e}")

        if self.chain.market_exists(args.market_id):
            return RelayResult(q, args.market_id, "exists", "already on-chain")
        try:
            tx = self.chain.create_categorical_market(args)  # type: ignore[attr-defined]
        except Exception as e:  # noqa: BLE001
            return RelayResult(q, args.market_id, "error", f"{type(e).__name__}: {e}")
        self.index_sink.record(MarketIndexRow.from_categorical(
            args, category=proposal.get("category", ""),
            outcomes=proposal.get("outcomes"), created_at=self._now()))
        return RelayResult(q, args.market_id, "submitted", "", tx_hash=tx)

    def run_categorical(self, proposals: List[Dict[str, Any]]) -> List[RelayResult]:
        if not self.chain.is_relayer():
            raise PermissionError(
                f"account {self.chain.account} is not an authorized relayer on the engine"
            )
        results = [self.relay_categorical_one(p) for p in proposals]
        counts: Dict[str, int] = {}
        for r in results:
            counts[r.status] = counts.get(r.status, 0) + 1
        logger.info("categorical relay complete: %s", counts)
        return results
