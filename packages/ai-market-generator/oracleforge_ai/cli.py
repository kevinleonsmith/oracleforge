"""CLI entrypoint: run the pipeline and emit market proposals as JSON.

    python -m oracleforge_ai.cli
    python -m oracleforge_ai.cli --format table
    python -m oracleforge_ai.cli --emit-calldata   # abi-ready createMarket args
"""
from __future__ import annotations

import argparse
import json

from .generator import MarketGenerator


def _calldata(p) -> dict:
    """Shape a proposal into the arguments MarketEngine.createMarket expects."""
    o = p.oracle
    return {
        "questionHash": p.question_hash,
        "closeAt": p.close_at,
        "aiProbBps": p.ai_prob_bps,
        "oracleParams": {
            "feed": o.feed,
            "fallbackFeed": o.fallback_feed,
            "threshold": o.threshold,
            "comparator": o.comparator,
            "maxStale": o.max_stale,
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="oracleforge-ai")
    ap.add_argument("--format", choices=["json", "table"], default="json")
    ap.add_argument("--emit-calldata", action="store_true", help="emit createMarket args")
    ap.add_argument("--min-confidence", type=float, default=0.45)
    args = ap.parse_args(argv)

    gen = MarketGenerator(min_confidence=args.min_confidence)
    proposals = gen.propose()

    if args.emit_calldata:
        print(json.dumps([_calldata(p) for p in proposals], indent=2))
        return 0

    if args.format == "table":
        print(f"{'CONF':>5}  {'PROB':>5}  {'CATEGORY':<8}  QUESTION")
        print("-" * 78)
        for p in proposals:
            print(f"{p.confidence:>5.2f}  {p.ai_prob_bps/100:>4.0f}%  {p.category:<8}  {p.question}")
        print(f"\n{len(proposals)} market(s) proposed.")
        return 0

    print(json.dumps([p.to_dict() for p in proposals], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
