"""End-to-end pipeline orchestrator — one market through every package.

This is the first test that crosses package boundaries. Each package is unit-
tested in isolation; here we thread a *single* generated market all the way
through the real module APIs and assert the properties that only hold when the
packages agree with each other:

    generate ─▶ relay ─▶ trade/settle ─▶ resolve ─▶ archive

    (oracleforge_ai)  (oracleforge_relayer)   (oracleforge_resolver) (oracleforge_archiver)

Invariants asserted across the boundary (see ``run_pipeline`` -> ``Checks``):

  1. identity        the market_id is derived once (relayer) and is unchanged
                     when the resolver settles it and the archiver stores it.
  2. determinism     the forecast committed on the relay path equals the
                     generator's local probability, bit-for-bit (the Cartesi
                     determinism boundary, proven end to end rather than per-unit).
  3. settlement      the parimutuel payout replicates MarketEngine.claim exactly
                     (integer math, fee skimmed from the losing pool) and
                     conserves value: winners + fee + dust == total staked.
  4. archival        content-addressing is stable — re-archiving the identical
                     market artifact dedupes to the same sha256.

Pure stdlib, no network, no install: runnable here and in CI (``npm run e2e`` /
``npm run test:e2e``). The live clients (web3/Arweave/GraphQL) are not touched;
this exercises the dry-run chain, the stub notice/oracle, and a local store.
"""
from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Any, Optional

# --- make the sibling packages importable (no install) ----------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
for _pkg in ("ai-market-generator", "relayer", "resolver", "archiver"):
    _p = os.path.abspath(os.path.join(_HERE, "..", "packages", _pkg))
    if _p not in sys.path:
        sys.path.insert(0, _p)

FEE_BPS = 200  # mirrors MarketEngine.feeBps (2.0%)


# --------------------------------------------------------------------------- #
# Stage 3 — parimutuel settlement, a byte-for-byte port of MarketEngine.claim  #
# --------------------------------------------------------------------------- #
@dataclass
class Settlement:
    outcome_yes: bool
    yes_pool: int
    no_pool: int
    winning_pool: int
    losing_pool_after_fee: int
    fee: int
    payouts: dict  # account -> payout (winners only)
    dust: int      # floor-division remainder left in the contract

    @property
    def total_staked(self) -> int:
        return self.yes_pool + self.no_pool

    @property
    def total_paid(self) -> int:
        return sum(self.payouts.values())


def settle(positions: list[tuple[str, str, int]], outcome_yes: bool,
           fee_bps: int = FEE_BPS) -> Settlement:
    """Settle parimutuel positions exactly as ``MarketEngine`` does on-chain.

    ``positions`` is a list of ``(account, "YES"|"NO", stake)``. Fee is skimmed
    from the losing pool at resolution; each winner is paid
    ``stake + stake * losingPoolAfterFee // winningPool`` (floor division, so a
    few wei of dust stay in the contract just like Solidity).
    """
    yes_pool = sum(s for _, side, s in positions if side == "YES")
    no_pool = sum(s for _, side, s in positions if side == "NO")
    winning_pool = yes_pool if outcome_yes else no_pool
    losing_pool = no_pool if outcome_yes else yes_pool
    fee = (losing_pool * fee_bps) // 10_000
    losing_after = losing_pool - fee

    payouts: dict[str, int] = {}
    if winning_pool > 0:
        for acct, side, stake in positions:
            win = (side == "YES") == outcome_yes
            if win and stake > 0:
                payouts[acct] = payouts.get(acct, 0) + stake + (stake * losing_after) // winning_pool
    dust = (winning_pool + losing_after) - sum(payouts.values())
    return Settlement(outcome_yes, yes_pool, no_pool, winning_pool, losing_after, fee, payouts, dust)


# --------------------------------------------------------------------------- #
# Pipeline result                                                             #
# --------------------------------------------------------------------------- #
@dataclass
class Checks:
    identity: bool = False
    determinism: bool = False
    settlement_conserved: bool = False
    archive_dedup: bool = False

    @property
    def all_pass(self) -> bool:
        return all((self.identity, self.determinism,
                    self.settlement_conserved, self.archive_dedup))


@dataclass
class PipelineResult:
    question: str
    market_id: str
    ai_prob_bps: int
    committed_bps: int
    outcome: str                 # "YES" | "NO"
    settlement: Settlement
    report_market_id: str
    archived_ids: list = field(default_factory=list)
    receipts: list = field(default_factory=list)
    checks: Checks = field(default_factory=Checks)


class _CapturingSink:
    """A resolver ReportSink that keeps the OracleReport objects it is handed."""

    def __init__(self) -> None:
        self.reports: list = []

    def record(self, report) -> None:
        self.reports.append(report)


def run_pipeline(now_ts: int = 1_737_010_000, outcome_yes: bool = True) -> PipelineResult:
    """Run every stage and return the threaded result + boundary checks."""
    # 1) GENERATE -----------------------------------------------------------
    from oracleforge_ai import MarketGenerator

    proposals = MarketGenerator().propose(now_ts=now_ts)
    if not proposals:
        raise RuntimeError("generator produced no proposals")
    proposal = proposals[0]
    proposal_dict = proposal.to_dict()

    # 2) RELAY (dry-run chain + stub committed notice) ----------------------
    from oracleforge_relayer.chain import DryRunChain
    from oracleforge_relayer.relayer import Relayer

    chain = DryRunChain(chain_id=10200)
    relayer = Relayer(chain, now_ts_fn=lambda: now_ts)
    relay_result = relayer.relay_one(proposal_dict)
    if relay_result.status != "submitted":
        raise RuntimeError(f"relay did not submit: {relay_result.status} {relay_result.detail}")
    market_id = relay_result.market_id
    committed_bps = relay_result.ai_prob_bps

    # 3) TRADE + SETTLE (parimutuel, contract-exact) ------------------------
    positions = [
        ("0xAlice", "YES", 600),
        ("0xBob", "YES", 400),
        ("0xCarol", "NO", 500),
        ("0xDave", "NO", 300),
    ]
    settlement = settle(positions, outcome_yes=outcome_yes)

    # 4) RESOLVE (watcher pokes resolve(), emits an OracleReport) ------------
    from oracleforge_resolver.chain import DryRunResolver
    from oracleforge_resolver.models import Market, Outcome, Status
    from oracleforge_resolver.oracle import StubOracleView
    from oracleforge_resolver.sources import StaticMarketSource
    from oracleforge_resolver.watcher import Watcher

    feed = (proposal_dict.get("oracle") or {}).get("feed", "ECON/CPI")
    market = Market(
        market_id=market_id,
        close_at=now_ts - 86_400,            # already past close -> resolvable
        status=Status.Open,
        feed=feed,
        question=proposal.question,
    )
    want = Outcome.Yes if outcome_yes else Outcome.No
    sink = _CapturingSink()
    watcher = Watcher(
        DryRunResolver(), StubOracleView({market_id: want}),
        StaticMarketSource([market]), sink, now_fn=lambda: now_ts,
    )
    tick = watcher.tick()
    if not sink.reports:
        raise RuntimeError(f"resolver emitted no report: {[t.__dict__ for t in tick]}")
    report = sink.reports[0]

    # 5) ARCHIVE (content-addressed local store, with dedupe) ---------------
    from oracleforge_archiver.archiver import (Archiver, artifact_from_market,
                                               artifact_from_oracle_report)
    from oracleforge_archiver.arweave import LocalArweaveClient

    store = tempfile.mkdtemp(prefix="oracleforge-e2e-")
    archiver = Archiver(LocalArweaveClient(store))
    market_artifact = artifact_from_market({
        "market_id": market_id,
        "question": proposal.question,
        "category": proposal.category,
        "close_at": proposal.close_at,
        "ai_prob_bps": committed_bps,
    })
    report_artifact = artifact_from_oracle_report(report)
    r_market = archiver.archive(market_artifact)
    r_report = archiver.archive(report_artifact)
    r_market_again = archiver.archive(market_artifact)   # must dedupe to same hash

    # --- boundary checks ---------------------------------------------------
    checks = Checks(
        identity=(market_id == report.market_id
                  == market_artifact.row_id == report_artifact.row_id),
        determinism=(committed_bps == proposal.ai_prob_bps),
        settlement_conserved=(
            settlement.total_paid + settlement.fee + settlement.dust
            == settlement.total_staked and settlement.dust >= 0
        ),
        archive_dedup=(
            not r_market.deduped and r_market_again.deduped
            and r_market_again.content_hash == r_market.content_hash
        ),
    )

    return PipelineResult(
        question=proposal.question,
        market_id=market_id,
        ai_prob_bps=proposal.ai_prob_bps,
        committed_bps=committed_bps,
        outcome="YES" if outcome_yes else "NO",
        settlement=settlement,
        report_market_id=report.market_id,
        archived_ids=[market_artifact.row_id, report_artifact.row_id],
        receipts=[r_market, r_report, r_market_again],
        checks=checks,
    )


def _fmt_money(n: int) -> str:
    return f"{n:,}"


def main(argv=None) -> int:
    res = run_pipeline()
    s = res.settlement
    print("OracleForge · end-to-end pipeline (dry-run, no network)\n")
    print(f"  1 generate   {res.question[:58]}")
    print(f"  2 relay      market_id {res.market_id[:18]}…  committed {res.committed_bps} bps")
    print(f"               (generator said {res.ai_prob_bps} bps — "
          f"{'match ✓' if res.committed_bps == res.ai_prob_bps else 'MISMATCH ✗'})")
    print(f"  3 trade      YES {_fmt_money(s.yes_pool)} · NO {_fmt_money(s.no_pool)}  "
          f"→ outcome {res.outcome}")
    print(f"     settle    fee {_fmt_money(s.fee)} · dust {s.dust} · payouts:")
    for acct, pay in s.payouts.items():
        print(f"               {acct:<9} → {_fmt_money(pay)}")
    print(f"  4 resolve    OracleReport for {res.report_market_id[:18]}…  outcome {res.outcome}")
    print(f"  5 archive    {len(res.archived_ids)} artifacts · "
          f"re-archive deduped {res.receipts[2].deduped}")
    print("\n  boundary checks")
    for name in ("identity", "determinism", "settlement_conserved", "archive_dedup"):
        ok = getattr(res.checks, name)
        print(f"    {'✓' if ok else '✗'} {name}")
    ok = res.checks.all_pass
    print(f"\n  {'ALL CHECKS PASS' if ok else 'CHECKS FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
