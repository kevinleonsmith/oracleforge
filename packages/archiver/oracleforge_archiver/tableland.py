"""Tableland write-back — record the Arweave tx id on the relational row.

``LogTablelandWriter`` collects the UPDATEs (dev/CI). ``RegistryTablelandWriter``
is the live path: a Tableland mutation is an on-chain tx against the TablelandTables
registry, so it must be signed — wired to web3 when the writer key is available.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Protocol

logger = logging.getLogger("oracleforge.archiver.tableland")


@dataclass
class WriteBack:
    table: str
    id_column: str
    row_id: str
    tx_column: str
    tx_id: str

    def sql(self) -> str:
        return (
            f"UPDATE {self.table} SET {self.tx_column}='{self.tx_id}' "
            f"WHERE {self.id_column}='{self.row_id}';"
        )


class TablelandWriter(Protocol):
    def set_arweave_tx(self, wb: WriteBack) -> None: ...


class LogTablelandWriter:
    def __init__(self):
        self.writes: List[WriteBack] = []

    def set_arweave_tx(self, wb: WriteBack) -> None:
        self.writes.append(wb)
        logger.info("tableland <- %s", wb.sql())


class RegistryTablelandWriter:
    """Signed mutation via the TablelandTables registry (web3). Live path."""

    def __init__(self, rpc_url: str, registry_address: str, table_id: int,
                 chain_id: int, private_key: str):
        self.rpc_url = rpc_url
        self.registry_address = registry_address
        self.table_id = table_id
        self.chain_id = chain_id
        self.private_key = private_key

    def set_arweave_tx(self, wb: WriteBack) -> None:  # pragma: no cover - needs chain + signer
        raise NotImplementedError(
            "RegistryTablelandWriter.set_arweave_tx: sign & send a mutate() tx to the "
            f"TablelandTables registry for statement: {wb.sql()}"
        )
