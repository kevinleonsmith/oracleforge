"""Arweave upload clients.

``LocalArweaveClient`` is a content-addressed directory store with a persisted
manifest — it behaves like Arweave for dev/CI/dry-run (permanent, dedupe by
content, retrievable) without a wallet or network. ``TurboArweaveClient`` is the
live path: a bundled upload via ArDrive Turbo / Irys (lazy-imported, signed with
a JWK).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Protocol, Tuple

logger = logging.getLogger("oracleforge.archiver.arweave")


def _txid_from_content(content: bytes) -> str:
    # 32-byte id, base64url (43 chars) — shaped like a real Arweave tx id, but
    # derived from content so the local store dedupes deterministically.
    digest = hashlib.sha256(b"arweave-local\x00" + content).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


class ArweaveClient(Protocol):
    def put(self, data: bytes, tags: List[Dict[str, str]], content_hash: str) -> Tuple[str, bool]: ...
    def url(self, tx_id: str) -> str: ...
    def get(self, tx_id: str) -> bytes: ...


class LocalArweaveClient:
    """Permanent-ish local store. Returns (tx_id, deduped)."""

    def __init__(self, store_dir: str, gateway: str = "local://"):
        self.dir = Path(store_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.gateway = gateway
        self._manifest_path = self.dir / "manifest.json"
        self._manifest: Dict[str, str] = {}
        if self._manifest_path.exists():
            try:
                self._manifest = json.loads(self._manifest_path.read_text())
            except ValueError:
                self._manifest = {}

    def put(self, data: bytes, tags: List[Dict[str, str]], content_hash: str) -> Tuple[str, bool]:
        if content_hash in self._manifest:
            return self._manifest[content_hash], True  # already archived
        tx_id = _txid_from_content(data)
        (self.dir / f"{tx_id}.data").write_bytes(data)
        (self.dir / f"{tx_id}.tags.json").write_text(json.dumps(tags, indent=2))
        self._manifest[content_hash] = tx_id
        self._manifest_path.write_text(json.dumps(self._manifest, indent=2))
        logger.info("stored %s (%d bytes)", tx_id, len(data))
        return tx_id, False

    def url(self, tx_id: str) -> str:
        return f"{self.gateway}{tx_id}"

    def get(self, tx_id: str) -> bytes:
        return (self.dir / f"{tx_id}.data").read_bytes()


class TurboArweaveClient:
    """Live bundled upload via ArDrive Turbo / Irys. Signed with a JWK.

    Lazy-imported so the stdlib core never needs the Arweave SDK. Reads the wallet
    from ARWEAVE_WALLET_JSON (path to a JWK keyfile).
    """

    def __init__(self, gateway: str = "https://arweave.net/", wallet_path: str | None = None):
        self.gateway = gateway.rstrip("/") + "/"
        self.wallet_path = wallet_path or os.environ.get("ARWEAVE_WALLET_JSON", "")

    def _signer(self):  # pragma: no cover - requires the arweave SDK + a wallet
        import arweave  # arweave-python-client

        if not self.wallet_path:
            raise RuntimeError("ARWEAVE_WALLET_JSON not set")
        return arweave.Wallet(self.wallet_path)

    def put(self, data: bytes, tags: List[Dict[str, str]], content_hash: str) -> Tuple[str, bool]:  # pragma: no cover
        import arweave

        wallet = self._signer()
        tx = arweave.Transaction(wallet, data=data)
        for t in tags:
            tx.add_tag(t["name"], t["value"])
        tx.sign()
        tx.send()
        return tx.id, False

    def url(self, tx_id: str) -> str:
        return f"{self.gateway}{tx_id}"

    def get(self, tx_id: str) -> bytes:  # pragma: no cover - network
        import requests

        r = requests.get(self.url(tx_id), timeout=30)
        r.raise_for_status()
        return r.content
