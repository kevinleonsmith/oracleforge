"""Clients for the remote inference service (stdlib urllib — no requests dep).

``RemoteEmbedder`` satisfies the AI package's ``Embedder`` protocol (``dim`` +
``embed``), so the generator uses GPU embeddings with a one-line swap:

    from oracleforge_inference.client import RemoteEmbedder
    gen = MarketGenerator(embedder=RemoteEmbedder("http://inference.akash:80"))
"""
from __future__ import annotations

import json
import urllib.request
from typing import List, Optional


class _Http:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def post(self, path: str, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path, data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())

    def get(self, path: str) -> dict:
        with urllib.request.urlopen(self.base_url + path, timeout=self.timeout) as r:
            return json.loads(r.read())


class RemoteEmbedder:
    def __init__(self, base_url: str, dim: Optional[int] = None, timeout: float = 30.0):
        self._http = _Http(base_url, timeout)
        self._dim = dim

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._dim = int(self._http.get("/health")["dim"])
        return self._dim

    def embed(self, text: str) -> List[float]:
        res = self._http.post("/embed", {"texts": [text]})
        self._dim = int(res["dim"])
        return res["embeddings"][0]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        res = self._http.post("/embed", {"texts": texts})
        self._dim = int(res["dim"])
        return res["embeddings"]


class RemoteDrafter:
    name = "remote"

    def __init__(self, base_url: str, timeout: float = 30.0):
        self._http = _Http(base_url, timeout)

    def draft(self, topic: str, signals: List[str], category: str = "") -> str:
        return self._http.post(
            "/draft", {"topic": topic, "signals": signals, "category": category}
        )["question"]
