"""Cartesi notice sources.

Two implementations of the same job — "give me the committed forecast notice for
this request":

* ``StubNoticeSource`` runs the identical deterministic forecaster in-process. The
  machine commits the output of exactly this function, so the stub reproduces the
  committed value bit-for-bit — enough to drive the relayer end-to-end (and the
  --dry-run demo) with no live rollup.
* ``GraphQLNoticeReader`` reads real notices from a running Cartesi node's GraphQL
  reader API, after an input has been advanced on-chain.

Which one is authoritative in production is the GraphQL reader; the stub is for
local dev, CI, and dry runs.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional


def hex_to_str(payload_hex: str) -> str:
    h = payload_hex[2:] if payload_hex.startswith("0x") else payload_hex
    return bytes.fromhex(h).decode("utf-8")


def str_to_hex(text: str) -> str:
    return "0x" + text.encode("utf-8").hex()


class StubNoticeSource:
    """In-process deterministic forecaster; mirrors the machine's committed notice."""

    name = "stub"

    def forecast(self, request: Dict[str, Any]) -> Dict[str, Any]:
        from oracleforge_ai.cartesi import monte_carlo_forecast  # lazy: core dep only here

        r = monte_carlo_forecast(
            request["question"],
            request.get("priors", [0.0]),
            base_rate=float(request.get("base_rate", 0.5)),
            samples=int(request.get("samples", 50_000)),
        )
        return {
            "op": "forecast",
            "question": request["question"],
            "prob_yes": r.prob_yes,
            "prob_bps": r.prob_bps,
            "ci_low_bps": r.ci_low_bps,
            "ci_high_bps": r.ci_high_bps,
            "samples": r.samples,
            "seed": r.seed,
            "input_hash": r.input_hash,
        }


class GraphQLNoticeReader:
    """Reads notices from a Cartesi node's GraphQL reader API.

    Sending the advance input (an on-chain InputBox tx) is the chain layer's job;
    this reader fetches the notices that input produced once the epoch settles.
    """

    name = "graphql"

    _QUERY = """
    query notices($inputIndex: Int!) {
      input(index: $inputIndex) {
        notices { edges { node { index payload } } }
      }
    }
    """

    def __init__(self, url: str):
        self.url = url

    def notices_for_input(self, input_index: int) -> List[Dict[str, Any]]:
        import requests  # lazy: only the live path needs it

        resp = requests.post(
            self.url,
            json={"query": self._QUERY, "variables": {"inputIndex": input_index}},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        edges = (
            data.get("data", {}).get("input", {}) or {}
        ).get("notices", {}).get("edges", [])
        out: List[Dict[str, Any]] = []
        for e in edges:
            payload_hex = e["node"]["payload"]
            try:
                out.append(json.loads(hex_to_str(payload_hex)))
            except (ValueError, UnicodeDecodeError):
                continue  # non-JSON notice; not ours
        return out

    def wait_for_forecast(
        self, input_index: int, timeout: float = 120.0, poll: float = 3.0
    ) -> Optional[Dict[str, Any]]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for n in self.notices_for_input(input_index):
                if n.get("op") == "forecast":
                    return n
            time.sleep(poll)
        return None
