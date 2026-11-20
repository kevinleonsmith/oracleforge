"""Inference service CLI.

    python -m oracleforge_inference.cli serve                 # run the server
    python -m oracleforge_inference.cli serve --port 8070
    python -m oracleforge_inference.cli probe --url http://localhost:8070   # one embed call
"""
from __future__ import annotations

import argparse
import json
import logging
import sys


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(prog="oracleforge-inference")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sv = sub.add_parser("serve", help="run the inference HTTP server")
    sv.add_argument("--host")
    sv.add_argument("--port", type=int)

    pr = sub.add_parser("probe", help="send one /embed + /health to a running server")
    pr.add_argument("--url", default="http://localhost:8070")

    args = ap.parse_args(argv)

    if args.cmd == "serve":
        from .config import Config
        from .server import serve
        from .service import build_engine

        cfg = Config.from_env()
        engine = build_engine(cfg.model, cfg.device, cfg.use_llm)
        h = engine.health()
        print(f"starting: embedder={h.embedder} dim={h.dim} drafter={h.drafter} gpu={h.gpu}")
        serve(engine, args.host or cfg.host, args.port or cfg.port)
        return 0

    if args.cmd == "probe":
        from .client import RemoteDrafter, RemoteEmbedder

        emb = RemoteEmbedder(args.url)
        vec = emb.embed("fed signals a possible rate cut")
        print(json.dumps({"dim": emb.dim, "first5": [round(x, 4) for x in vec[:5]]}, indent=2))
        print("draft:", RemoteDrafter(args.url).draft("us-rates", ["CPI cooling"], "MACRO"))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
