"""Relayer CLI.

    python -m oracleforge_relayer.cli --dry-run           # generate + relay (no chain)
    python -m oracleforge_relayer.cli --dry-run --scalar   # relay sample scalar markets
    python -m oracleforge_relayer.cli --proposals p.json   # relay a saved proposal set
    python -m oracleforge_relayer.cli --submit             # submit on-chain (needs env)

Env for live submission: RELAYER_RPC_URL, RELAYER_PK, MARKET_ENGINE_ADDRESS,
NEXT_PUBLIC_CHAIN (gnosis|chiado). See .env.example.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys


def _load_generator_proposals(limit: int | None, min_conf: float) -> list[dict]:
    import time

    # Make the sibling AI package importable when running from source.
    here = os.path.dirname(__file__)
    ai = os.path.abspath(os.path.join(here, "..", "..", "ai-market-generator"))
    if ai not in sys.path:
        sys.path.insert(0, ai)
    from oracleforge_ai import MarketGenerator

    # Generate against the current time so close_at is in the future for the
    # real-time relayer (the generator's own default now_ts is a fixed constant
    # used for test determinism).
    gen = MarketGenerator(min_confidence=min_conf)
    proposals = [p.to_dict() for p in gen.propose(now_ts=int(time.time()))]
    return proposals[:limit] if limit else proposals


def _sample_scalar_proposals(now: int) -> list[dict]:
    day = 86400
    return [
        {"question": "Where will ETH close at the end of the quarter?", "category": "CRYPTO",
         "close_at": now + 30 * day, "band": {"lower": 3000, "upper": 5000},
         "oracle": {"feed": "ETH/USD", "target_decimals": 0, "max_stale": 3600}},
        {"question": "US CPI year-over-year for the reference month?", "category": "MACRO",
         "close_at": now + 20 * day, "band": {"lower": 2, "upper": 5},
         "oracle": {"feed": "ECON/CPI", "target_decimals": 2, "max_stale": 86400}},
    ]


def _print_scalar_table(results) -> None:
    print(f"{'STATUS':<10} {'MARKET_ID':<14} QUESTION")
    print("-" * 80)
    for r in results:
        print(f"{r.status:<10} {(r.market_id or '')[:12]:<14} {r.question[:48]}")
        if r.detail:
            print(f"{'':<10} └─ {r.detail}")


def _print_table(results) -> None:
    print(f"{'STATUS':<10} {'PROB':>5}  {'MARKET_ID':<14} QUESTION")
    print("-" * 86)
    for r in results:
        mid = (r.market_id or "")[:12]
        prob = f"{r.ai_prob_bps/100:.0f}%" if r.ai_prob_bps is not None else "  -"
        print(f"{r.status:<10} {prob:>5}  {mid:<14} {r.question[:46]}")
        if r.detail:
            print(f"{'':<10} └─ {r.detail}")


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="oracleforge-relayer")
    ap.add_argument("--dry-run", action="store_true", help="no chain writes (default if no env)")
    ap.add_argument("--submit", action="store_true", help="submit createMarket on-chain")
    ap.add_argument("--scalar", action="store_true", help="relay sample scalar (range) markets")
    ap.add_argument("--proposals", help="path to a proposals JSON file (else run the generator)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--min-confidence", type=float, default=0.45)
    args = ap.parse_args(argv)

    from .config import Config
    from .feeds import FeedRegistry
    from .notices import GraphQLNoticeReader, StubNoticeSource
    from .relayer import Relayer

    cfg = Config.from_env()

    # Scalar dry-run demo: map sample range markets to ScalarMarketEngine creations.
    if args.scalar and not args.submit:
        import time as _t
        from .chain import DryRunChain

        relayer = Relayer(DryRunChain(chain_id=cfg.chain_id), FeedRegistry())
        results = relayer.run_scalar(_sample_scalar_proposals(int(_t.time())))
        _print_scalar_table(results)
        submitted = sum(1 for r in results if r.status == "submitted")
        print(f"\n{submitted}/{len(results)} scalar market(s) would be submitted (dry-run).")
        return 0

    # proposals
    if args.proposals:
        with open(args.proposals) as f:
            proposals = json.load(f)
    else:
        proposals = _load_generator_proposals(args.limit, args.min_confidence)

    # chain
    live = args.submit and not args.dry_run
    if live:
        if not (cfg.rpc_url and cfg.private_key and cfg.engine_address):
            ap.error("--submit needs RELAYER_RPC_URL, RELAYER_PK and MARKET_ENGINE_ADDRESS")
        from .chain import GnosisChain

        chain = GnosisChain(cfg.rpc_url, cfg.private_key, cfg.engine_address, cfg.chain_id)
    else:
        from .chain import DryRunChain

        chain = DryRunChain(chain_id=cfg.chain_id)

    # notice source
    if cfg.notice_source == "graphql" and live:
        source = GraphQLNoticeReader(cfg.cartesi_graphql_url)
        relayer = Relayer(chain, FeedRegistry(), notice_source=source, graphql_reader=source)
    else:
        relayer = Relayer(chain, FeedRegistry(), notice_source=StubNoticeSource())

    try:
        results = relayer.run(proposals)
    except PermissionError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    _print_table(results)
    submitted = sum(1 for r in results if r.status == "submitted")
    print(f"\n{submitted}/{len(results)} market(s) {'submitted' if live else 'would be submitted (dry-run)'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
