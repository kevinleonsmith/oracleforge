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
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

# --- make the sibling packages importable (no install) ----------------------
_HERE = os.path.dirname(os.path.abspath(__file__))
for _pkg in ("ai-market-generator", "relayer", "resolver", "archiver"):
    _p = os.path.abspath(os.path.join(_HERE, "..", "packages", _pkg))
    if _p not in sys.path:
        sys.path.insert(0, _p)

FEE_BPS = 200  # mirrors MarketEngine.feeBps (2.0%)

# The reference trade scenario, shared by the pure pipeline and the anvil devnet
# so both settle the identical positions: (account, "YES"|"NO", stake).
DEMO_POSITIONS: list[tuple[str, str, int]] = [
    ("0xAlice", "YES", 600),
    ("0xBob", "YES", 400),
    ("0xCarol", "NO", 500),
    ("0xDave", "NO", 300),
]


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
# Stage 3b — SCALAR (range) settlement, a byte-for-byte port of               #
#            ScalarMarketEngine._payoutPools + claim (and the one-sided void). #
# --------------------------------------------------------------------------- #
# The reference scalar scenario, shared by the anvil devnet so both settle the
# identical book: (account, "LONG"|"SHORT", stake).
SCALAR_DEMO_POSITIONS: list[tuple[str, str, int]] = [
    ("0xAlice", "LONG", 600),
    ("0xBob", "LONG", 400),
    ("0xCarol", "SHORT", 500),
    ("0xDave", "SHORT", 300),
]
SCALAR_DEMO_BAND = (100, 200)  # [lower, upper]


@dataclass
class ScalarSettlement:
    settled_value: int        # clamped into [lower, upper]
    lower: int
    upper: int
    long_pool: int
    short_pool: int
    fee: int
    long_payout: int          # LONG side's collective share (after fee)
    short_payout: int         # SHORT side's collective share (remainder)
    payouts: dict             # account -> payout (every staker; may be 0)
    dust: int                 # floor-division remainder left in the contract
    void: bool                # one-sided book -> refunded, nothing settled

    @property
    def total_staked(self) -> int:
        return self.long_pool + self.short_pool

    @property
    def total_paid(self) -> int:
        return sum(self.payouts.values())


def scalar_settle(positions: list[tuple[str, str, int]], settled_value: int,
                  lower: int, upper: int, fee_bps: int = FEE_BPS) -> ScalarSettlement:
    """Settle scalar (range) positions exactly as ``ScalarMarketEngine`` does.

    ``positions`` is a list of ``(account, "LONG"|"SHORT", stake)``. The value is
    clamped into ``[lower, upper]`` and converted to a fraction
    ``f = (cv - lower) / (upper - lower)``; the pot minus the fee is split
    ``long = distributable * f`` / ``short = remainder``, and each account takes
    its pro-rata share of its side (floor division per side, summed — the exact
    order of operations in ``claim``). A one-sided book **voids**: every principal
    is refunded, no fee. Mirrors the contract's integer math to the wei.
    """
    long_pool = sum(s for _, side, s in positions if side == "LONG")
    short_pool = sum(s for _, side, s in positions if side == "SHORT")
    accounts = list(dict.fromkeys(a for a, _, _ in positions))

    # One-sided book -> void and refund principal (deterministic; skips the pot math).
    if long_pool == 0 or short_pool == 0:
        refunds: dict[str, int] = defaultdict(int)
        for acct, _side, stake in positions:
            refunds[acct] += stake
        cv = lower if settled_value < lower else (upper if settled_value > upper else settled_value)
        return ScalarSettlement(cv, lower, upper, long_pool, short_pool, 0, 0, 0,
                                {a: refunds[a] for a in accounts}, 0, void=True)

    cv = lower if settled_value < lower else (upper if settled_value > upper else settled_value)
    pot = long_pool + short_pool
    fee = (pot * fee_bps) // 10_000
    distributable = pot - fee
    num = cv - lower
    den = upper - lower
    long_payout = (distributable * num) // den
    short_payout = distributable - long_payout  # remainder, no dust lost at this split

    # Aggregate stake per (account, side) first, then one floor-division per side —
    # exactly as claim() reads stakeOf[market][account][side].
    long_stake: dict[str, int] = defaultdict(int)
    short_stake: dict[str, int] = defaultdict(int)
    for acct, side, stake in positions:
        (long_stake if side == "LONG" else short_stake)[acct] += stake

    payouts: dict[str, int] = {}
    for acct in accounts:
        pay = (long_payout * long_stake[acct]) // long_pool
        pay += (short_payout * short_stake[acct]) // short_pool
        payouts[acct] = pay

    dust = distributable - sum(payouts.values())
    return ScalarSettlement(cv, lower, upper, long_pool, short_pool, fee,
                            long_payout, short_payout, payouts, dust, void=False)


# --------------------------------------------------------------------------- #
# Stage 3c — CATEGORICAL (N-outcome) settlement, a byte-for-byte port of       #
#            CategoricalMarketEngine resolve + claim (and the no-winner void). #
# --------------------------------------------------------------------------- #
# The reference categorical scenario, shared by the anvil devnet so both settle
# the identical book: (account, outcome_index, stake).
CATEGORICAL_DEMO_POSITIONS: list[tuple[str, int, int]] = [
    ("0xAlice", 0, 600),
    ("0xBob", 0, 400),
    ("0xCarol", 1, 500),
    ("0xDave", 2, 500),
]
CATEGORICAL_DEMO_OUTCOMES = 3  # outcomeCount


@dataclass
class CategoricalSettlement:
    winning_outcome: int
    outcome_count: int
    pools: list                # staked total per outcome index
    winning_pool: int
    losing_pool_net: int       # distributable losing pool after fee
    fee: int
    payouts: dict              # account -> payout (winners only, or all on void)
    dust: int                  # floor-division remainder left in the contract
    void: bool                 # no winner / invalid -> refunded, nothing settled

    @property
    def total_staked(self) -> int:
        return sum(self.pools)

    @property
    def total_paid(self) -> int:
        return sum(self.payouts.values())


def categorical_settle(positions: list[tuple[str, int, int]], winning_outcome: int,
                       outcome_count: int, fee_bps: int = FEE_BPS) -> CategoricalSettlement:
    """Settle categorical (N-outcome) positions exactly as
    ``CategoricalMarketEngine`` does on-chain.

    ``positions`` is a list of ``(account, outcome_index, stake)``. The winning
    pool takes the entire losing pot (minus the fee) pro-rata to stake; each
    winner is paid ``stake + stake * losingPoolNet // winningPool`` (floor
    division, so a few wei of dust stay in the contract, as in Solidity). An
    out-of-range winner (``>= outcome_count``, e.g. the 0xFF invalid sentinel) or a
    winning pool with no stake **voids**: every principal is refunded, no fee.
    """
    pools = [0] * outcome_count
    for _acct, outcome, stake in positions:
        if 0 <= outcome < outcome_count:
            pools[outcome] += stake
    accounts = list(dict.fromkeys(a for a, _, _ in positions))

    winning_pool = pools[winning_outcome] if 0 <= winning_outcome < outcome_count else 0

    # Out-of-range winner or no stake on the winner -> void & refund principal.
    if winning_outcome >= outcome_count or winning_pool == 0:
        refunds: dict[str, int] = defaultdict(int)
        for acct, _outcome, stake in positions:
            refunds[acct] += stake
        return CategoricalSettlement(
            winning_outcome, outcome_count, pools, winning_pool, 0, 0,
            {a: refunds[a] for a in accounts}, 0, void=True)

    total_pot = sum(pools)
    losing_pool = total_pot - winning_pool
    fee = (losing_pool * fee_bps) // 10_000
    losing_net = losing_pool - fee

    # Aggregate winning-outcome stake per account, then one floor-division each —
    # exactly as claim() reads stakeOf[market][account][winningOutcome].
    win_stake: dict[str, int] = defaultdict(int)
    for acct, outcome, stake in positions:
        if outcome == winning_outcome:
            win_stake[acct] += stake

    payouts: dict[str, int] = {}
    for acct in accounts:
        s = win_stake[acct]
        if s > 0:  # losers get nothing (their claim reverts on-chain)
            payouts[acct] = s + (s * losing_net) // winning_pool

    dust = (winning_pool + losing_net) - sum(payouts.values())
    return CategoricalSettlement(
        winning_outcome, outcome_count, pools, winning_pool, losing_net, fee,
        payouts, dust, void=False)


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
    settlement = settle(DEMO_POSITIONS, outcome_yes=outcome_yes)

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


# --------------------------------------------------------------------------- #
# Cross-engine thread — the same question, relayed through all three engines    #
# --------------------------------------------------------------------------- #
@dataclass
class MultiEnginePipelineResult:
    question: str
    close_at: int
    market_id: str                 # identical across the three engines
    binary: Settlement
    scalar: ScalarSettlement
    categorical: CategoricalSettlement
    index_rows: dict               # market_type -> the markets-index INSERT
    ids_match: bool                # the three relayers derived the same market_id
    all_conserved: bool            # every engine's settlement balances
    types_distinct: bool           # the index rows are self-describing by type


def _conserves(s) -> bool:
    return s.total_paid + s.fee + s.dust == s.total_staked and s.dust >= 0


def run_multi_engine_pipeline(now_ts: int = 1_737_010_000) -> MultiEnginePipelineResult:
    """Relay one question through the binary, scalar and categorical engines and
    assert the cross-engine properties: (1) the marketId derivation is identical
    across all three engines for the same (questionHash, closeAt, chainId), so the
    relayer's dedupe is cross-consistent; (2) each engine settles its own book with
    value conserved; (3) the markets-index rows are self-describing by market_type
    even though the id namespace coincides.
    """
    from oracleforge_relayer.feeds import FeedRegistry
    from oracleforge_relayer.index import MarketIndexRow
    from oracleforge_relayer.mapping import (
        build_categorical_create_market_args,
        build_create_market_args,
        build_scalar_create_market_args,
    )

    reg = FeedRegistry()
    chain_id = 10200
    question = "Will the reference benchmark resolve in range this quarter?"
    close_at = now_ts + 30 * 86_400

    binary_args = build_create_market_args(
        {"question": question, "category": "MACRO", "close_at": close_at,
         "oracle": {"feed": "EUR/USD", "threshold": 110_000_000, "comparator": 0,
                    "fallback_feed": None, "max_stale": 3600}},
        6700, chain_id, reg, now_ts,
    )
    scalar_args = build_scalar_create_market_args(
        {"question": question, "category": "MACRO", "close_at": close_at,
         "band": {"lower": 100, "upper": 200, "unit": ""},
         "oracle": {"feed": "ETH/USD", "target_decimals": 0, "fallback_feed": None, "max_stale": 3600}},
        chain_id, reg, now_ts,
    )
    categorical_args = build_categorical_create_market_args(
        {"question": question, "category": "SPORTS", "close_at": close_at,
         "outcomes": ["A", "B", "C"],
         "oracle": {"feed": "FUNCTIONS/SPORTS", "fallback_feed": None, "max_stale": 3600}},
        chain_id, reg, now_ts,
    )

    ids = {binary_args.market_id, scalar_args.market_id, categorical_args.market_id}
    ids_match = len(ids) == 1

    binary = settle(DEMO_POSITIONS, outcome_yes=True)
    scalar = scalar_settle(SCALAR_DEMO_POSITIONS, 150, *SCALAR_DEMO_BAND)
    categorical = categorical_settle(
        CATEGORICAL_DEMO_POSITIONS, 0, CATEGORICAL_DEMO_OUTCOMES)

    index_rows = {
        "binary": MarketIndexRow.from_binary(binary_args, category="MACRO", created_at=now_ts),
        "scalar": MarketIndexRow.from_scalar(scalar_args, category="MACRO", unit="", created_at=now_ts),
        "categorical": MarketIndexRow.from_categorical(
            categorical_args, category="SPORTS", outcomes=["A", "B", "C"], created_at=now_ts),
    }
    types_distinct = (
        {r.market_type for r in index_rows.values()} == {"binary", "scalar", "categorical"}
        and all(r.market_id == binary_args.market_id for r in index_rows.values())
    )

    return MultiEnginePipelineResult(
        question=question, close_at=close_at, market_id=binary_args.market_id,
        binary=binary, scalar=scalar, categorical=categorical, index_rows=index_rows,
        ids_match=ids_match,
        all_conserved=_conserves(binary) and _conserves(scalar) and _conserves(categorical),
        types_distinct=types_distinct,
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

    # Cross-engine thread: one question through all three engines.
    me = run_multi_engine_pipeline()
    print("\n  cross-engine thread (one question → binary + scalar + categorical)")
    print(f"    market_id {me.market_id[:18]}…  identical across engines "
          f"{'✓' if me.ids_match else '✗'}")
    print(f"    binary {_fmt_money(me.binary.total_paid)} paid · "
          f"scalar {_fmt_money(me.scalar.total_paid)} paid · "
          f"categorical {_fmt_money(me.categorical.total_paid)} paid")
    for name, flag in (("ids_match", me.ids_match), ("all_conserved", me.all_conserved),
                       ("types_distinct", me.types_distinct)):
        print(f"    {'✓' if flag else '✗'} {name}")
    me_ok = me.ids_match and me.all_conserved and me.types_distinct
    print(f"\n  {'ALL CHECKS PASS' if ok and me_ok else 'CHECKS FAILED'}")
    return 0 if ok and me_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
