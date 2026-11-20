"""Anvil devnet variant — settle against the REAL deployed MarketEngine.

The pure pipeline (`integration/pipeline.py`) settles positions with a Python
*port* of `MarketEngine.claim`. This variant removes the port from the trust
path: it boots a local **anvil** node, deploys the actual Solidity contracts,
runs the full on-chain lifecycle

    deploy → createMarket → takePosition ×N → (advance time) → resolve → claim ×N

driving every step with `cast`, then asserts the **on-chain payouts equal the
Python port to the wei** for the same scenario (`pipeline.DEMO_POSITIONS`). If
the port ever drifts from the contract, this goes red.

Pure stdlib + the Foundry toolchain (anvil/forge/cast). No external node, no
funded key: anvil's deterministic dev accounts are used (the standard, publicly
documented test keys — devnet only, never real funds).

    python3 devnet.py          # run it (also: npm run devnet)
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..")))
from pipeline import DEMO_POSITIONS, FEE_BPS, settle  # noqa: E402

CONTRACTS = os.path.abspath(os.path.join(_HERE, "..", "..", "packages", "contracts"))
# Ephemeral port per run so repeated/parallel runs never collide on a stale node.
PORT = int(os.environ.get("DEVNET_PORT") or random.randint(8600, 8990))
RPC = os.environ.get("DEVNET_RPC") or f"http://127.0.0.1:{PORT}"

# Standard anvil/hardhat deterministic dev accounts (public test keys, devnet only).
ACCOUNTS = [
    ("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
     "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"),  # 0 deployer/admin
    ("0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
     "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"),  # 1 Alice
    ("0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
     "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"),  # 2 Bob
    ("0x90F79bf6EB2c4f870365E785982E1f101E93b906",
     "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6"),  # 3 Carol
    ("0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
     "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a"),  # 4 Dave
]
# Map the pipeline's named traders onto dev accounts 1..4 (deployer is account 0).
TRADER_ACCT = {"0xAlice": 1, "0xBob": 2, "0xCarol": 3, "0xDave": 4}
SIDE_ENUM = {"NO": 0, "YES": 1}  # MarketEngine.Side { No, Yes }
OUTCOME_YES = 1                   # IOracleAdapter.Outcome { Pending, Yes, No, Invalid }


class DevnetError(RuntimeError):
    pass


def _run(cmd: list[str], **kw) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        raise DevnetError(f"$ {' '.join(cmd)}\n{p.stdout}\n{p.stderr}")
    return p.stdout.strip()


def cast(*args: str) -> str:
    return _run(["cast", *args, "--rpc-url", RPC])


def cast_send(pk: str, to: str, sig: str, *args: str) -> dict:
    out = _run(["cast", "send", to, sig, *args, "--private-key", pk,
                "--rpc-url", RPC, "--json"])
    return json.loads(out)


def rpc(method: str, *params: str) -> None:
    _run(["cast", "rpc", method, *params, "--rpc-url", RPC])


def forge_create(contract: str, *ctor_args: str) -> str:
    cmd = ["forge", "create", contract, "--rpc-url", RPC,
           "--private-key", ACCOUNTS[0][1], "--broadcast", "--json"]
    if ctor_args:
        cmd += ["--constructor-args", *ctor_args]
    out = _run(cmd, cwd=CONTRACTS)
    # stdout holds a (pretty-printed) JSON object, possibly with a compile line
    # before it and/or a warning line after it — decode just the first object.
    brace = out.find("{")
    if brace == -1:
        raise DevnetError(f"no JSON in forge create output:\n{out}")
    obj, _ = json.JSONDecoder().raw_decode(out[brace:])
    return obj["deployedTo"]


def topic0(sig: str) -> str:
    return _run(["cast", "keccak", sig])


def _log_by_topic0(receipt: dict, sig: str) -> dict | None:
    want = topic0(sig).lower()
    for log in receipt.get("logs", []):
        topics = log.get("topics", [])
        if topics and topics[0].lower() == want:
            return log
    return None


# --------------------------------------------------------------------------- #
@dataclass
class Devnet:
    proc: subprocess.Popen

    @classmethod
    def start(cls) -> "Devnet":
        logf = tempfile.NamedTemporaryFile(
            prefix="oracleforge-anvil-", suffix=".log", delete=False)
        proc = subprocess.Popen(
            ["anvil", "--port", str(PORT), "--silent"],
            stdout=logf, stderr=subprocess.STDOUT,
        )
        for _ in range(50):
            if proc.poll() is not None:  # anvil exited (e.g. port in use)
                raise DevnetError(f"anvil exited early; see {logf.name}")
            try:
                cast("block-number")
                return cls(proc)
            except DevnetError:
                time.sleep(0.2)
        proc.terminate()
        raise DevnetError("anvil did not become ready")

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def run_devnet(outcome_yes: bool = True) -> dict:
    """Deploy + exercise the lifecycle on anvil; return actual vs expected."""
    gov = ACCOUNTS[0][0]
    pk0 = ACCOUNTS[0][1]

    # --- deploy the real contracts ----------------------------------------
    collateral = forge_create("src/mocks/MockERC20.sol:MockERC20",
                              "OracleForge USD", "ofUSD", "18")
    treasury = forge_create("src/Treasury.sol:Treasury", gov)
    oracle = forge_create("src/mocks/MockOracleAdapter.sol:MockOracleAdapter")
    engine = forge_create("src/MarketEngine.sol:MarketEngine",
                          collateral, oracle, treasury, gov)

    # --- create a market (closeAt in the near future) ---------------------
    now = int(cast("block", "latest", "--field", "timestamp"), 0)
    close_at = now + 3600
    qhash = topic0("Will ofUSD settle this parimutuel on-chain?")
    rc = cast_send(pk0, engine, "createMarket(bytes32,uint64,uint16,bytes)",
                   qhash, str(close_at), "6700", "0x")
    created = _log_by_topic0(rc, "MarketCreated(bytes32,bytes32,uint64,uint16)")
    if not created:
        raise DevnetError("no MarketCreated event")
    market_id = created["topics"][1]  # indexed marketId

    # --- fund + approve + take positions ----------------------------------
    for acct, side, stake in DEMO_POSITIONS:
        i = TRADER_ACCT[acct]
        addr, pk = ACCOUNTS[i]
        cast_send(pk0, collateral, "mint(address,uint256)", addr, str(stake))
        cast_send(pk, collateral, "approve(address,uint256)", engine, str(stake))
        cast_send(pk, engine, "takePosition(bytes32,uint8,uint256)",
                  market_id, str(SIDE_ENUM[side]), str(stake))

    # --- set the outcome, advance past close, resolve ---------------------
    out_enum = OUTCOME_YES if outcome_yes else 2  # 2 = No
    cast_send(pk0, oracle, "setOutcome(bytes32,uint8)", market_id, str(out_enum))
    rpc("evm_increaseTime", "4000")
    rpc("evm_mine")
    rrc = cast_send(pk0, engine, "resolve(bytes32)", market_id)
    resolved = _log_by_topic0(rrc, "MarketResolved(bytes32,uint8,uint256)")
    # data = abi.encode(uint8 outcome, uint256 feePaid): two words; fee is the 2nd.
    onchain_fee = int(resolved["data"][-64:], 16)

    # --- each winning account claims; read the actual payout --------------
    onchain_payouts: dict[str, int] = {}
    for acct, side, _stake in DEMO_POSITIONS:
        if (side == "YES") != outcome_yes:
            continue  # loser — claim would revert ("no winnings")
        i = TRADER_ACCT[acct]
        crc = cast_send(ACCOUNTS[i][1], engine, "claim(bytes32)", market_id)
        claimed = _log_by_topic0(crc, "Claimed(bytes32,address,uint256)")
        onchain_payouts[acct] = int(claimed["data"], 16)  # payout (non-indexed)

    expected = settle(DEMO_POSITIONS, outcome_yes=outcome_yes)
    return {
        "market_id": market_id,
        "engine": engine,
        "onchain_payouts": onchain_payouts,
        "onchain_fee": onchain_fee,
        "expected_payouts": dict(expected.payouts),
        "expected_fee": expected.fee,
        "parity": (onchain_payouts == dict(expected.payouts)
                   and onchain_fee == expected.fee),
    }


def main(argv=None) -> int:
    dev = Devnet.start()
    try:
        res = run_devnet()
    finally:
        dev.stop()

    print("OracleForge · anvil devnet — settlement parity (real MarketEngine)\n")
    print(f"  engine     {res['engine']}")
    print(f"  market_id  {res['market_id'][:18]}…\n")
    print(f"  {'ACCOUNT':<9} {'ON-CHAIN':>10} {'PORT':>10}  {'':>3}")
    for acct in res["expected_payouts"]:
        oc = res["onchain_payouts"].get(acct)
        ex = res["expected_payouts"][acct]
        print(f"  {acct:<9} {oc:>10} {ex:>10}  {'✓' if oc == ex else '✗'}")
    fee_ok = res["onchain_fee"] == res["expected_fee"]
    print(f"  {'fee':<9} {res['onchain_fee']:>10} {res['expected_fee']:>10}  "
          f"{'✓' if fee_ok else '✗'}")
    print(f"\n  {'PARITY: on-chain == Python port' if res['parity'] else 'PARITY FAILED'}")
    return 0 if res["parity"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
