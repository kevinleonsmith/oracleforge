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


def _sample_categorical_markets(now: int):
    """A representative spread of categorical (N-outcome) markets for the dry-run."""
    day = 86400
    return [
        Market("0x" + "a1" * 32, now - day, Status.Open, feed="SPORTS/CHAMPION"),  # ready -> winner
        Market("0x" + "b2" * 32, now - day, Status.Open, feed="ELECTION/SEAT"),    # ready -> void
        Market("0x" + "c3" * 32, now + 5 * day, Status.Open, feed="AWARD/BEST"),   # not closed -> wait
        Market("0x" + "d4" * 32, now - day, Status.Open, feed="LEAGUE/TABLE"),     # closed but pending
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


def _print_categorical(results) -> None:
    print(f"{'STATUS':<9} {'ACTION':<8} {'WIN':<5} {'MARKET_ID':<14} DETAIL")
    print("-" * 78)
    for r in results:
        win = "VOID" if r.predicted_outcome is None else str(r.predicted_outcome)
        print(f"{r.status:<9} {r.action:<8} {win:<5} {r.market_id[:12]:<14} {r.detail}")


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="oracleforge-resolver")
    ap.add_argument("--dry-run", action="store_true", help="one tick over sample markets, no chain")
    ap.add_argument("--scalar", action="store_true", help="dry-run over scalar (range) markets")
    ap.add_argument("--categorical", action="store_true", help="dry-run over categorical (N-outcome) markets")
    ap.add_argument("--watch", action="store_true", help="live loop against the chain")
    ap.add_argument("--interval", type=float, default=None)
    ap.add_argument("--once", action="store_true", help="live: a single tick then exit")
    ap.add_argument("--tableland", action="store_true",
                    help="archive settlements as oracle_reports INSERTs (dry-run: prints the SQL)")
    ap.add_argument("--positions", action="store_true",
                    help="dry-run: index sample PositionTaken events as positions INSERTs")
    args = ap.parse_args(argv)

    # Positions indexer dry-run: turn sample trades into positions INSERTs.
    if args.positions and not args.watch:
        import time as _t
        from .archive import LogTablelandMutator
        from .positions import ClaimEvent, PositionEvent, PositionIndexer, StubPositionEventSource

        now = int(_t.time())
        events = [
            PositionEvent.from_dict({"market_id": "0xA7F3", "account": "0xAlice", "side": 1,
                                     "amount": 600_000000, "tx_hash": "0xt1", "created_at": now}),
            PositionEvent.from_dict({"market_id": "0xA7F3", "account": "0xBob", "side": 0,
                                     "amount": 400_000000, "tx_hash": "0xt2", "created_at": now}),
        ]
        mutator = LogTablelandMutator()
        indexer = PositionIndexer(StubPositionEventSource(events), mutator=mutator)
        rows = indexer.index()
        # a sample claim then flips one account's position to claimed.
        claims = indexer.index_claims([ClaimEvent("0xA7F3", "0xAlice")])
        print(f"indexed {len(rows)} position(s), {len(claims)} claim(s)")
        print("\npositions -> Tableland (would sign & send):")
        for stmt in mutator.statements:
            print(f"  {stmt}")
        return 0

    from .archive import LogReportSink, TablelandReportSink
    from .config import Config
    from .watcher import Watcher

    def _make_sink():
        return TablelandReportSink() if args.tableland else LogReportSink()

    def _print_archive(sink) -> None:
        if isinstance(sink, TablelandReportSink) and sink.mutator.statements:
            # Each settlement emits an oracle_reports INSERT and a markets catalog
            # transition (CLOSED on a propose, RESOLVED/INVALID on a finalize).
            print("\nsettlement -> Tableland (oracle_reports + markets, would sign & send):")
            for stmt in sink.mutator.statements:
                print(f"  {stmt}")

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
            sink = _make_sink()
            watcher = ScalarWatcher(
                DryRunResolver(), StubScalarOracleView(values),
                StaticMarketSource(markets), sink, now_fn=lambda: now,
            )
            results = watcher.tick()
            _print_scalar(results)
            resolved = sum(1 for r in results if r.status == "resolved")
            print(f"\n{resolved} scalar market(s) resolved (dry-run).")
            _print_archive(sink)
            return 0

        if args.categorical:
            from .oracle import StubCategoricalOracleView
            from .watcher import CategoricalWatcher

            markets = _sample_categorical_markets(now)
            outcomes = {
                markets[0].market_id: (True, 2),    # ready -> outcome 2 wins
                markets[1].market_id: (True, 0xFF),  # ready -> invalid sentinel (void)
                markets[3].market_id: (False, 0),    # feed not ready
            }
            sink = _make_sink()
            watcher = CategoricalWatcher(
                DryRunResolver(), StubCategoricalOracleView(outcomes),
                StaticMarketSource(markets), sink, now_fn=lambda: now,
            )
            results = watcher.tick()
            _print_categorical(results)
            resolved = sum(1 for r in results if r.status == "resolved")
            print(f"\n{resolved} categorical market(s) resolved (dry-run).")
            _print_archive(sink)
            return 0

        from .oracle import StubOracleView

        markets = _sample_markets(now)
        outcomes = {
            markets[0].market_id: Outcome.Yes,
            markets[1].market_id: Outcome.No,
            markets[3].market_id: Outcome.Pending,
        }
        sink = _make_sink()
        watcher = Watcher(
            DryRunResolver(), StubOracleView(outcomes),
            StaticMarketSource(markets), sink, now_fn=lambda: now,
        )
        results = watcher.tick()
        _print(results)
        resolved = sum(1 for r in results if r.status == "resolved")
        print(f"\n{resolved} market(s) resolved (dry-run).")
        _print_archive(sink)
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

    if args.tableland:
        from .archive import RegistryTablelandMutator

        if not cfg.private_key:
            ap.error("--tableland (live) needs RESOLVER_PK to sign the oracle_reports write")
        mutator = RegistryTablelandMutator(
            cfg.rpc_url, cfg.oracle_address or "", 0, cfg.chain_id, cfg.private_key)
        sink: object = TablelandReportSink(cfg.reports_table, mutator)
    else:
        sink = LogReportSink()
    watcher = Watcher(resolver, oracle_view, source, sink, challenge_window=window)

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
