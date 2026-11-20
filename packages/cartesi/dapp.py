"""OracleForge Cartesi Rollups backend (machine entrypoint).

Runs inside the Cartesi Machine. Polls the Rollup HTTP Server for advance/inspect
requests, decodes the hex payload, runs the deterministic forecast via
``handler.process``, and posts the results back as notices (advance) or reports
(inspect). All the forecasting logic is in ``handler.py`` / ``oracleforge_ai`` so
this file is only I/O glue.

Payload shape (JSON, hex-encoded on the wire):
    {"op": "forecast", "question": "...", "priors": [0.4], "base_rate": 0.5}
    {"op": "bayes", "prior_prob": 0.5, "likelihood_ratio": 3.0}
"""
from os import environ

import json
import logging

import requests

from handler import hex_to_str, process, str_to_hex

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("oracleforge-cartesi")

ROLLUP_SERVER = environ.get("ROLLUP_HTTP_SERVER_URL", "http://127.0.0.1:5004")
logger.info("starting; rollup server at %s", ROLLUP_SERVER)


def _emit(kind: str, payload: dict) -> None:
    """Post a notice or report back to the rollup server."""
    body = {"payload": str_to_hex(json.dumps(payload, sort_keys=True))}
    resp = requests.post(f"{ROLLUP_SERVER}/{kind}", json=body)
    logger.info("emitted %s -> %s", kind, resp.status_code)


def _decode(data: dict):
    return json.loads(hex_to_str(data["payload"]))


def handle_advance(data: dict) -> str:
    logger.info("advance from %s", data.get("metadata", {}).get("msg_sender"))
    try:
        req = _decode(data)
    except Exception as e:  # noqa: BLE001 - surface any decode error as a report
        _emit("report", {"error": f"undecodable payload: {e}"})
        return "reject"

    outputs = process(req, inspect=False)
    rejected = any(o["kind"] == "report" and "error" in o["payload"] for o in outputs)
    for o in outputs:
        _emit(o["kind"], o["payload"])
    return "reject" if rejected else "accept"


def handle_inspect(data: dict) -> str:
    try:
        req = _decode(data)
    except Exception as e:  # noqa: BLE001
        _emit("report", {"error": f"undecodable payload: {e}"})
        return "accept"

    for o in process(req, inspect=True):
        _emit("report", o["payload"])
    return "accept"


HANDLERS = {"advance_state": handle_advance, "inspect_state": handle_inspect}


def main() -> None:
    finish = {"status": "accept"}
    while True:
        resp = requests.post(f"{ROLLUP_SERVER}/finish", json=finish)
        if resp.status_code == 202:
            # no pending request; keep polling
            continue
        rollup = resp.json()
        handler = HANDLERS[rollup["request_type"]]
        finish["status"] = handler(rollup["data"])


if __name__ == "__main__":
    main()
