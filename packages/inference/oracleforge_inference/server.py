"""Stdlib HTTP server for the inference engine.

No FastAPI/uvicorn dependency — keeps the GPU image small and the service testable
with nothing installed. Endpoints: GET /health, POST /embed, POST /draft.
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .schemas import DraftRequest, EmbedRequest
from .service import InferenceEngine

logger = logging.getLogger("oracleforge.inference.server")


def make_handler(engine: InferenceEngine):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, obj: dict) -> None:
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read(self) -> dict:
            n = int(self.headers.get("Content-Length", 0) or 0)
            return json.loads(self.rfile.read(n) or b"{}")

        def log_message(self, *args):  # silence default stderr logging
            pass

        def do_GET(self):
            if self.path == "/health":
                self._send(200, engine.health().to_dict())
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            try:
                if self.path == "/embed":
                    self._send(200, engine.embed(EmbedRequest.from_dict(self._read())).to_dict())
                elif self.path == "/draft":
                    self._send(200, engine.draft(DraftRequest.from_dict(self._read())).to_dict())
                else:
                    self._send(404, {"error": "not found"})
            except ValueError as e:
                self._send(400, {"error": str(e)})
            except Exception as e:  # noqa: BLE001
                self._send(500, {"error": f"{type(e).__name__}: {e}"})

    return Handler


def make_server(engine: InferenceEngine, host: str = "0.0.0.0", port: int = 8070) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(engine))


def serve(engine: InferenceEngine, host: str = "0.0.0.0", port: int = 8070) -> None:
    srv = make_server(engine, host, port)
    logger.info("inference server listening on %s:%d", host, port)
    srv.serve_forever()
