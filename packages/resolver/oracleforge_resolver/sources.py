"""Market sources — where the watcher discovers candidate markets.

The watcher only needs id/close_at/status, so any index works. Live deployments
query Tableland (the markets table) or read the engine's MarketCreated logs; the
static source drives dev/CI/dry-run.
"""
from __future__ import annotations

from typing import Any, Dict, List, Protocol

from .models import Market, status_from


class MarketSource(Protocol):
    def open_markets(self) -> List[Market]: ...


class StaticMarketSource:
    """Fixed market list for dry-run and tests."""

    def __init__(self, markets: List[Market]):
        self._markets = markets

    def open_markets(self) -> List[Market]:
        # a real source filters server-side; here we hand back everything unsettled
        return list(self._markets)


class TablelandMarketSource:
    """Reads unsettled markets from the Tableland gateway (read-only HTTP)."""

    def __init__(self, gateway_url: str, markets_table: str):
        self.gateway_url = gateway_url.rstrip("/")
        self.table = markets_table

    def open_markets(self) -> List[Market]:
        import requests  # lazy: live path only

        sql = (
            f"SELECT market_id, close_at, status, outcome FROM {self.table} "
            f"WHERE status IN ('OPEN','CLOSED')"
        )
        resp = requests.get(
            f"{self.gateway_url}/api/v1/query", params={"statement": sql}, timeout=15
        )
        resp.raise_for_status()
        return [self._row(r) for r in resp.json()]

    @staticmethod
    def _row(r: Dict[str, Any]) -> Market:
        return Market(
            market_id=str(r["market_id"]),
            close_at=int(r["close_at"]),
            status=status_from(r.get("status", "OPEN")),
            outcome=int(r.get("outcome") or 0),
        )
