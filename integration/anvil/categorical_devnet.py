"""Anvil devnet — settle a CATEGORICAL (N-outcome) market against the REAL contract.

The siblings ``devnet.py`` and ``scalar_devnet.py`` prove the binary and scalar
engines pay exactly what their Python ports compute. This one does the same for the
**categorical** engine — winner-take-all across N mutually-exclusive outcomes: it
boots a local anvil node, deploys the actual ``CategoricalMarketEngine`` +
``MockCategoricalOracle``, and runs the full lifecycle

    deploy → createMarket(N) → takePosition(outcome) ×N
           → oracle.set(winner) → (advance time) → resolve → claim ×N

driving every step with ``cast``, then asserts the **on-chain payouts equal the
Python port (`pipeline.categorical_settle`) to the wei**. If the port ever drifts
from the contract, this goes red.

Three scenarios exercise the distinct code paths:
  - **winner** a funded outcome wins → that pool splits the losing pot pro-rata,
              losers' claims revert (so only winners are claimed);
  - **void_empty** the winning outcome has no stake → void, every principal refunded;
  - **void_invalid** the oracle reports the 0xFF sentinel → void, refunded.

Reuses ``devnet.py``'s node/cast plumbing. Pure stdlib + the Foundry toolchain;
anvil's deterministic dev accounts, devnet only, never real funds.

    python3 categorical_devnet.py   # run it (also: npm run devnet:categorical)
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..")))
from pipeline import (  # noqa: E402
    CATEGORICAL_DEMO_OUTCOMES,
    CATEGORICAL_DEMO_POSITIONS,
    categorical_settle,
)

# Reuse the binary devnet's node lifecycle, cast wrappers, dev accounts, deploy.
from devnet import (  # noqa: E402
    ACCOUNTS,
    TRADER_ACCT,
    Devnet,
    DevnetError,
    cast,
    cast_send,
    forge_create,
    rpc,
    topic0,
    _log_by_topic0,
)

INVALID_SENTINEL = 0xFF


# A scenario is (name, outcome_count, positions, winner, use_invalid).
# void_empty uses a 4th outcome nobody funded (the demo book stakes 0/1/2), so the
# winning pool is empty -> void; the other two use the 3-outcome demo book.
SCENARIOS = {
    "winner": (CATEGORICAL_DEMO_OUTCOMES, CATEGORICAL_DEMO_POSITIONS, 0, False),
    "void_empty": (CATEGORICAL_DEMO_OUTCOMES + 1, CATEGORICAL_DEMO_POSITIONS, 3, False),
    "void_invalid": (CATEGORICAL_DEMO_OUTCOMES, CATEGORICAL_DEMO_POSITIONS, 0, True),
}


def run_categorical_devnet(scenario: str = "winner") -> dict:
    """Deploy + exercise the categorical lifecycle on anvil; actual vs expected."""
    outcome_count, positions, winner, use_invalid = SCENARIOS[scenario]
    gov = ACCOUNTS[0][0]
    pk0 = ACCOUNTS[0][1]

    # --- deploy the real contracts ----------------------------------------
    collateral = forge_create("src/mocks/MockERC20.sol:MockERC20",
                              "OracleForge USD", "ofUSD", "18")
    treasury = forge_create("src/Treasury.sol:Treasury", gov)
    oracle = forge_create("src/mocks/MockCategoricalOracle.sol:MockCategoricalOracle")
    engine = forge_create("src/CategoricalMarketEngine.sol:CategoricalMarketEngine",
                          collateral, oracle, treasury, gov)

    # --- create a categorical market (outcomeCount + closeAt) -------------
    now = int(cast("block", "latest", "--field", "timestamp"), 0)
    close_at = now + 3600
    qhash = topic0(f"Which outcome wins? ({scenario})")
    rc = cast_send(pk0, engine, "createMarket(bytes32,uint64,uint8,bytes)",
                   qhash, str(close_at), str(outcome_count), "0x")
    created = _log_by_topic0(rc, "MarketCreated(bytes32,bytes32,uint64,uint8)")
    if not created:
        raise DevnetError("no MarketCreated event")
    market_id = created["topics"][1]  # indexed marketId

    # --- fund + approve + take positions on chosen outcomes ---------------
    for acct, outcome, stake in positions:
        i = TRADER_ACCT[acct]
        addr, pk = ACCOUNTS[i]
        cast_send(pk0, collateral, "mint(address,uint256)", addr, str(stake))
        cast_send(pk, collateral, "approve(address,uint256)", engine, str(stake))
        cast_send(pk, engine, "takePosition(bytes32,uint8,uint256)",
                  market_id, str(outcome), str(stake))

    # --- set the oracle outcome, advance past close, resolve --------------
    if use_invalid:
        cast_send(pk0, oracle, "setInvalid(bytes32)", market_id)
    else:
        cast_send(pk0, oracle, "set(bytes32,uint8)", market_id, str(winner))
    rpc("evm_increaseTime", "4000")
    rpc("evm_mine")
    rrc = cast_send(pk0, engine, "resolve(bytes32)", market_id)

    voided = _log_by_topic0(rrc, "MarketVoided(bytes32)") is not None
    onchain_fee = 0
    if not voided:
        resolved = _log_by_topic0(rrc, "MarketResolved(bytes32,uint8,uint256)")
        if not resolved:
            raise DevnetError("neither MarketResolved nor MarketVoided emitted")
        # data = abi.encode(uint8 winningOutcome, uint256 fee): fee is the 2nd word.
        onchain_fee = int(resolved["data"][-64:], 16)

    # Expected from the Python port. Its payouts are exactly the claimable accounts
    # (winners when resolved, everyone when voided) — losers' on-chain claims revert.
    expected = categorical_settle(
        positions, INVALID_SENTINEL if use_invalid else winner, outcome_count)

    onchain_payouts: dict[str, int] = {}
    for acct in expected.payouts:
        i = TRADER_ACCT[acct]
        crc = cast_send(ACCOUNTS[i][1], engine, "claim(bytes32)", market_id)
        claimed = _log_by_topic0(crc, "Claimed(bytes32,address,uint256)")
        onchain_payouts[acct] = int(claimed["data"], 16)  # payout (non-indexed)

    return {
        "scenario": scenario,
        "market_id": market_id,
        "engine": engine,
        "voided": voided,
        "onchain_payouts": onchain_payouts,
        "onchain_fee": onchain_fee,
        "expected_payouts": dict(expected.payouts),
        "expected_fee": expected.fee,
        "expected_void": expected.void,
        "parity": (onchain_payouts == dict(expected.payouts)
                   and onchain_fee == expected.fee
                   and voided == expected.void),
    }


def main(argv=None) -> int:
    dev = Devnet.start()
    all_ok = True
    try:
        for scenario in ("winner", "void_empty", "void_invalid"):
            res = run_categorical_devnet(scenario)
            all_ok = all_ok and res["parity"]
            tag = "VOID" if res["voided"] else f"fee {res['onchain_fee']}"
            print(f"OracleForge · anvil devnet — categorical parity "
                  f"[{scenario}]  ({tag})")
            print(f"  engine {res['engine']}  market {res['market_id'][:14]}…")
            print(f"  {'ACCOUNT':<9} {'ON-CHAIN':>10} {'PORT':>10}")
            for acct in res["expected_payouts"]:
                oc = res["onchain_payouts"].get(acct)
                ex = res["expected_payouts"][acct]
                print(f"  {acct:<9} {oc:>10} {ex:>10}  {'✓' if oc == ex else '✗'}")
            print(f"  {'PARITY ✓' if res['parity'] else 'PARITY FAILED ✗'}\n")
    finally:
        dev.stop()
    print("ALL CATEGORICAL SCENARIOS AT PARITY" if all_ok else "CATEGORICAL PARITY FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
