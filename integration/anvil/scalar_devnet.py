"""Anvil devnet — settle a SCALAR (range) market against the REAL contract.

The sibling ``devnet.py`` proves the *binary* ``MarketEngine`` pays exactly what
the Python parimutuel port computes. This one does the same for the **scalar**
engine, whose payout is a continuum rather than winner-take-all: it boots a local
anvil node, deploys the actual ``ScalarMarketEngine`` + ``MockScalarOracle``, and
runs the full lifecycle

    deploy → createMarket(band) → takePosition LONG/SHORT ×N
           → oracle.set(value) → (advance time) → resolve → claim ×N

driving every step with ``cast``, then asserts the **on-chain payouts equal the
Python port (`pipeline.scalar_settle`) to the wei**. The scalar settlement math
lived only in Solidity and a float UI preview; this removes any trust in the
integer port by checking it against the contract it mirrors. If the port ever
drifts, this goes red.

Three scenarios exercise the distinct code paths:
  - **mid**   value inside the band → both sides paid, dust retained;
  - **clamp** value above the band → LONG takes all, SHORT claims 0 (no revert,
              unlike the binary loser);
  - **void**  one-sided book → market voids, every principal refunded.

Reuses ``devnet.py``'s node/cast plumbing. Pure stdlib + the Foundry toolchain;
anvil's deterministic dev accounts, devnet only, never real funds.

    python3 scalar_devnet.py        # run it (also: npm run devnet:scalar)
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..")))
from pipeline import SCALAR_DEMO_BAND, SCALAR_DEMO_POSITIONS, scalar_settle  # noqa: E402

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

SCALAR_SIDE = {"SHORT": 0, "LONG": 1}  # ScalarMarketEngine.Side { Short, Long }


# A scenario is (name, lower, upper, positions, settlement_value).
SCENARIOS = {
    "mid": (SCALAR_DEMO_BAND[0], SCALAR_DEMO_BAND[1], SCALAR_DEMO_POSITIONS, 150),
    "clamp": (SCALAR_DEMO_BAND[0], SCALAR_DEMO_BAND[1], SCALAR_DEMO_POSITIONS, 999),
    "void": (SCALAR_DEMO_BAND[0], SCALAR_DEMO_BAND[1],
             [("0xAlice", "LONG", 600), ("0xBob", "LONG", 400)], 150),
}


def run_scalar_devnet(scenario: str = "mid") -> dict:
    """Deploy + exercise the scalar lifecycle on anvil; return actual vs expected."""
    lower, upper, positions, value = SCENARIOS[scenario]
    gov = ACCOUNTS[0][0]
    pk0 = ACCOUNTS[0][1]

    # --- deploy the real contracts ----------------------------------------
    collateral = forge_create("src/mocks/MockERC20.sol:MockERC20",
                              "OracleForge USD", "ofUSD", "18")
    treasury = forge_create("src/Treasury.sol:Treasury", gov)
    oracle = forge_create("src/mocks/MockScalarOracle.sol:MockScalarOracle")
    engine = forge_create("src/ScalarMarketEngine.sol:ScalarMarketEngine",
                          collateral, oracle, treasury, gov)

    # --- create a scalar market (band + closeAt in the near future) -------
    now = int(cast("block", "latest", "--field", "timestamp"), 0)
    close_at = now + 3600
    qhash = topic0(f"Where will ofUSD settle in [{lower},{upper}]? ({scenario})")
    rc = cast_send(pk0, engine, "createMarket(bytes32,uint64,int256,int256,bytes)",
                   qhash, str(close_at), str(lower), str(upper), "0x")
    created = _log_by_topic0(
        rc, "MarketCreated(bytes32,bytes32,uint64,int256,int256)")
    if not created:
        raise DevnetError("no MarketCreated event")
    market_id = created["topics"][1]  # indexed marketId

    # --- fund + approve + take LONG/SHORT positions -----------------------
    for acct, side, stake in positions:
        i = TRADER_ACCT[acct]
        addr, pk = ACCOUNTS[i]
        cast_send(pk0, collateral, "mint(address,uint256)", addr, str(stake))
        cast_send(pk, collateral, "approve(address,uint256)", engine, str(stake))
        cast_send(pk, engine, "takePosition(bytes32,uint8,uint256)",
                  market_id, str(SCALAR_SIDE[side]), str(stake))

    # --- set the oracle value, advance past close, resolve ----------------
    cast_send(pk0, oracle, "set(bytes32,int256)", market_id, str(value))
    rpc("evm_increaseTime", "4000")
    rpc("evm_mine")
    rrc = cast_send(pk0, engine, "resolve(bytes32)", market_id)

    voided = _log_by_topic0(rrc, "MarketVoided(bytes32)") is not None
    onchain_fee = 0
    if not voided:
        resolved = _log_by_topic0(rrc, "MarketResolved(bytes32,int256,uint256)")
        if not resolved:
            raise DevnetError("neither MarketResolved nor MarketVoided emitted")
        # data = abi.encode(int256 settledValue, uint256 fee): fee is the 2nd word.
        onchain_fee = int(resolved["data"][-64:], 16)

    # --- every staker claims (scalar losers don't revert — they claim 0) ---
    onchain_payouts: dict[str, int] = {}
    for acct in dict.fromkeys(a for a, _, _ in positions):
        i = TRADER_ACCT[acct]
        crc = cast_send(ACCOUNTS[i][1], engine, "claim(bytes32)", market_id)
        claimed = _log_by_topic0(crc, "Claimed(bytes32,address,uint256)")
        onchain_payouts[acct] = int(claimed["data"], 16)  # payout (non-indexed)

    expected = scalar_settle(positions, value, lower, upper)
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
        for scenario in ("mid", "clamp", "void"):
            res = run_scalar_devnet(scenario)
            all_ok = all_ok and res["parity"]
            tag = "VOID" if res["voided"] else f"fee {res['onchain_fee']}"
            print(f"OracleForge · anvil devnet — scalar parity "
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
    print("ALL SCALAR SCENARIOS AT PARITY" if all_ok else "SCALAR PARITY FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
