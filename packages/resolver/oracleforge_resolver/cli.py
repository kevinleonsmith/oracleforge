"""Resolution-watcher CLI.

    python -m oracleforge_resolver.cli --dry-run           # one tick over a sample set
    python -m oracleforge_resolver.cli --dry-run --scalar  # same, for scalar markets
    python -m oracleforge_resolver.cli --watch             # live loop (needs env)
    python -m oracleforge_resolver.cli --watch --interval 15

Env for live operation: RESOLVER_RPC_URL, RESOLVER_PK, MARKET_ENGINE_ADDRESS,
NEXT_PUBLIC_CHAIN, and a markets source (MARKETS_TABLE + gateway). See .env.example.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from .models import Market, Outcome, Status


def _sample_markets(now: int):
    """A representative spread for the dry-run."""
    day = 86400
    return [
        Market("0x" + "a1" * 32, now - day, Status.Open, feed="EUR/USD"),       # ready -> YES
        Market("0x" + "b2" * 32, now - day, Status.Open, feed="ECON/CPI"),      # ready -> NO
        Market("0x" + "c3" * 32, now + 5 * day, Status.Open, feed="BTC/DVOL"),  # not closed -> wait
        Market("0x" + "d4" * 32, now - day, Status.Open, feed="FUNCTIONS/NOAA"),# closed but pending
        Market("0x" + "e5" * 32, now - 2 * day, Status.Resolved, outcome=1),    # already settled
    ]


def _sample_scalar_markets(now: int):
    """A representative spread of scalar (range) markets for the dry-run."""
    day = 86400
    return [
        Market("0x" + "a1" * 32, now - day, Status.Open, feed="ETH/USD"),       # ready -> value
        Market("0x" + "c3" * 32, now + 5 * day, Status.Open, feed="BTC/USD"),   # not closed -> wait
        Market("0x" + "d4" * 32, now - day, Status.Open, feed="GAS/GWEI"),      # closed but pending
        Market("0x" + "e5" * 32, now - 2 * day, Status.Resolved),              # already settled
    ]


def _print(results) -> None:
    print(f"{'STATUS':<9} {'ACTION':<8} {'OUT':<4} {'MARKET_ID':<14} DETAIL")
    print("-" * 78)
    for r in results:
        out = {1: "YES", 0: "NO", None: "-"}.get(r.predicted_outcome, "VOID")
        print(f"{r.status:<9} {r.action:<8} {out:<4} {r.market_id[:12]:<14} {r.detail}")


def _print_scalar(results) -> None:
    print(f"{'STATUS':<9} {'ACTION':<8} {'MARKET_ID':<14} DETAIL")
    print("-" * 70)
    for r in results:
        print(f"{r.status:<9} {r.action:<8} {r.market_id[:12]:<14} {r.detail}")


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="oracleforge-resolver")
    ap.add_argument("--dry-run", action="store_true", help="one tick over sample markets, no chain")
    ap.add_argument("--scalar", action="store_true", help="dry-run over scalar (range) markets")
    ap.add_argument("--watch", action="store_true", help="live loop against the chain")
    ap.add_argument("--interval", type=float, default=None)
    ap.add_argument("--once", action="store_true", help="live: a single tick then exit")
    args = ap.parse_args(argv)

    from .archive import LogReportSink
    from .config import Config
    from .watcher import Watcher

    if not args.watch:  # default: dry-run
        from .chain import DryRunResolver
        from .sources import StaticMarketSource

        now = int(time.time())

        if args.scalar:
            from .oracle import StubScalarOracleView
            from .watcher import ScalarWatcher

            markets = _sample_scalar_markets(now)
            values = {
                markets[0].market_id: (True, 4200),  # ready -> propose value
                markets[2].market_id: (False, 0),    # feed not ready
            }
            watcher = ScalarWatcher(
                DryRunResolver(), StubScalarOracleView(values),
                StaticMarketSource(markets), LogReportSink(), now_fn=lambda: now,
            )
            results = watcher.tick()
            _print_scalar(results)
            resolved = sum(1 for r in results if r.status == "resolved")
            print(f"\n{resolved} scalar market(s) resolved (dry-run).")
            return 0

        from .oracle import StubOracleView

        markets = _sample_markets(now)
        outcomes = {
            markets[0].market_id: Outcome.Yes,
            markets[1].market_id: Outcome.No,
            markets[3].market_id: Outcome.Pending,
        }
        watcher = Watcher(
            DryRunResolver(), StubOracleView(outcomes),
            StaticMarketSource(markets), LogReportSink(), now_fn=lambda: now,
        )
        results = watcher.tick()
        _print(results)
        resolved = sum(1 for r in results if r.status == "resolved")
        print(f"\n{resolved} market(s) resolved (dry-run).")
        return 0

    # live
    cfg = Config.from_env()
    if not (cfg.rpc_url and cfg.engine_address):
        ap.error("--watch needs RESOLVER_RPC_URL and MARKET_ENGINE_ADDRESS")
    from .chain import GnosisResolver
    from .oracle import ChainOracleView
    from .sources import TablelandMarketSource

    resolver = GnosisResolver(cfg.rpc_url, cfg.engine_address, cfg.chain_id, cfg.private_key or None)
    oracle_addr = cfg.oracle_address or resolver.oracle_address()
    oracle_view = ChainOracleView(resolver.w3, oracle_addr)
    source = TablelandMarketSource(cfg.tableland_gateway, cfg.markets_table)
    window = resolver.challenge_window()  # 0 => instant finalization, like before
    watcher = Watcher(resolver, oracle_view, source, LogReportSink(), challenge_window=window)

    try:
        if args.once:
            _print(watcher.tick())
        else:
            watcher.watch(interval=args.interval or cfg.interval)
    except KeyboardInterrupt:
        print("stopped", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
