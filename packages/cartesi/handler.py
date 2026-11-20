"""Pure request handling for the OracleForge Cartesi dApp.

Kept free of any rollup / HTTP imports so it can be unit-tested off-machine and
reused unchanged inside the Cartesi Machine. The rollup I/O loop lives in
``dapp.py`` and calls ``process()``.

Determinism contract: every output here is a pure function of the request bytes.
``monte_carlo_forecast`` seeds its PRNG from a hash of the inputs, so the notice
committed on-chain is byte-identical on every node and on fraud-proof replay.
"""
from __future__ import annotations

from typing import Any, Dict, List

from oracleforge_ai.cartesi import bayesian_update, monte_carlo_forecast

# ----------------------------------------------------------------- hex helpers


def hex_to_str(payload_hex: str) -> str:
    """Decode a 0x-prefixed hex payload (as delivered by the rollup) to text."""
    h = payload_hex[2:] if payload_hex.startswith("0x") else payload_hex
    return bytes.fromhex(h).decode("utf-8")


def str_to_hex(text: str) -> str:
    """Encode text to a 0x-prefixed hex payload (as expected by the rollup)."""
    return "0x" + text.encode("utf-8").hex()


# -------------------------------------------------------------------- handling

# An "output" is {"kind": "notice"|"report", "payload": <json-able dict>}.
# Notices are committed to the rollup's state (fraud-proofable, consumable
# on-chain); reports are read-only diagnostics (used for inspect + errors).
Output = Dict[str, Any]


def _forecast(req: Dict[str, Any], kind: str) -> List[Output]:
    question = req["question"]
    priors = req.get("priors", [0.0])
    base_rate = float(req.get("base_rate", 0.5))
    samples = int(req.get("samples", 50_000))

    r = monte_carlo_forecast(question, priors, base_rate=base_rate, samples=samples)
    payload = {
        "op": "forecast",
        "question": question,
        "prob_yes": r.prob_yes,
        "prob_bps": r.prob_bps,
        "samples": r.samples,
        "seed": r.seed,
        "input_hash": r.input_hash,
    }
    return [{"kind": kind, "payload": payload}]


def _bayes(req: Dict[str, Any], kind: str) -> List[Output]:
    prior = float(req["prior_prob"])
    lr = float(req["likelihood_ratio"])
    posterior = bayesian_update(prior, lr)
    return [
        {
            "kind": kind,
            "payload": {
                "op": "bayes",
                "prior_prob": prior,
                "likelihood_ratio": lr,
                "posterior": posterior,
                "posterior_bps": max(0, min(10_000, round(posterior * 10_000))),
            },
        }
    ]


def process(req: Dict[str, Any], inspect: bool = False) -> List[Output]:
    """Dispatch a decoded request to the right deterministic routine.

    advance (inspect=False): committed results are emitted as **notices**.
    inspect (inspect=True):  results are emitted as read-only **reports**.
    """
    # On an advance, the committed result is a notice; on inspect, a report.
    result_kind = "report" if inspect else "notice"
    op = req.get("op", "forecast")

    try:
        if op == "forecast":
            return _forecast(req, result_kind)
        if op == "bayes":
            return _bayes(req, result_kind)
        return [{"kind": "report", "payload": {"error": f"unknown op: {op!r}"}}]
    except (KeyError, ValueError, TypeError) as e:
        return [{"kind": "report", "payload": {"error": f"{type(e).__name__}: {e}"}}]
