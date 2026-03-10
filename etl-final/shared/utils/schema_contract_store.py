"""
Persistent schema contract store backends for ETL services.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from shared.models import SchemaContract

from .ch_identifiers import quote_table_name, sanitize_table_name
from .clickhouse_schemas import ClickHouseSchemaManager


logger = logging.getLogger(__name__)


class SchemaContractStore(Protocol):
    def get_contract(
        self,
        source_id: Optional[str],
        schema_version: Optional[str],
        schema_id: Optional[str] = None,
    ) -> Optional[SchemaContract]:
        ...


class NullSchemaContractStore:
    def get_contract(
        self,
        source_id: Optional[str],
        schema_version: Optional[str],
        schema_id: Optional[str] = None,
    ) -> Optional[SchemaContract]:
        return None


class ClickHouseSchemaContractStore:
    def __init__(self, client: Any, table_name: str = "schema_contract_registry"):
        self.client = client
        self.table_name = sanitize_table_name(table_name)
        self.quoted_table = quote_table_name(self.table_name)
        try:
            ClickHouseSchemaManager(client).create_schema_contract_registry_table(self.table_name)
        except Exception as exc:
            logger.warning("[SchemaStore] Failed to ensure ClickHouse registry table: %s", exc)

    def get_contract(
        self,
        source_id: Optional[str],
        schema_version: Optional[str],
        schema_id: Optional[str] = None,
    ) -> Optional[SchemaContract]:
        if not schema_version:
            return None
        try:
            params: Dict[str, Any] = {"schema_version": str(schema_version)}
            where = ["schema_version = %(schema_version)s"]
            if source_id:
                where.append("source_id = %(source_id)s")
                params["source_id"] = str(source_id)
            if schema_id:
                where.append("schema_id = %(schema_id)s")
                params["schema_id"] = str(schema_id)

            query = f"""
            SELECT contract_json
            FROM {self.quoted_table}
            WHERE {" AND ".join(where)}
            ORDER BY updated_at DESC
            LIMIT 1
            """
            rows = self.client.execute(query, params)
            if not rows:
                return None
            raw_contract = rows[0][0] if isinstance(rows[0], (list, tuple)) else rows[0].get("contract_json")
            if not raw_contract:
                return None
            parsed = json.loads(raw_contract)
            return SchemaContract.from_dict(parsed)
        except Exception as exc:
            logger.warning("[SchemaStore] ClickHouse contract lookup failed: %s", exc)
            return None


class FileSchemaContractStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self._cached_mtime: Optional[float] = None
        self._records: List[Dict[str, Any]] = []

    def _load(self) -> None:
        if not self.path.exists():
            self._records = []
            self._cached_mtime = None
            return

        stat = self.path.stat()
        if self._cached_mtime is not None and stat.st_mtime == self._cached_mtime:
            return

        content = self.path.read_text(encoding="utf-8")
        data = json.loads(content) if content.strip() else []
        records: List[Dict[str, Any]] = []

        if isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict):
                    records.append(entry)
        elif isinstance(data, dict):
            for _, entry in data.items():
                if isinstance(entry, dict):
                    records.append(entry)

        self._records = records
        self._cached_mtime = stat.st_mtime

    def get_contract(
        self,
        source_id: Optional[str],
        schema_version: Optional[str],
        schema_id: Optional[str] = None,
    ) -> Optional[SchemaContract]:
        if not schema_version:
            return None
        try:
            self._load()
            for entry in self._records:
                if source_id and str(entry.get("source_id")) != str(source_id):
                    continue
                if schema_id and str(entry.get("schema_id")) != str(schema_id):
                    continue
                if str(entry.get("schema_version")) != str(schema_version):
                    continue
                contract_data = entry.get("contract") or entry.get("schema_contract")
                if isinstance(contract_data, dict):
                    return SchemaContract.from_dict(contract_data)
            return None
        except Exception as exc:
            logger.warning("[SchemaStore] File contract lookup failed: %s", exc)
            return None


class HttpSchemaContractStore:
    def __init__(self, base_url: str, timeout_seconds: float = 3.0):
        self.base_url = str(base_url).rstrip("/")
        self.timeout_seconds = float(timeout_seconds)

    def get_contract(
        self,
        source_id: Optional[str],
        schema_version: Optional[str],
        schema_id: Optional[str] = None,
    ) -> Optional[SchemaContract]:
        if not schema_version:
            return None
        try:
            params = {"schema_version": str(schema_version)}
            if source_id:
                params["source_id"] = str(source_id)
            if schema_id:
                params["schema_id"] = str(schema_id)
            query = urlencode(params)
            url = f"{self.base_url}/contracts?{query}"
            request = Request(url, method="GET")
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8")
            data = json.loads(payload)
            contract_data = data.get("contract") if isinstance(data, dict) else None
            if isinstance(contract_data, dict):
                return SchemaContract.from_dict(contract_data)
            if isinstance(data, dict) and "schema_id" in data and "version" in data and "fields" in data:
                return SchemaContract.from_dict(data)
            return None
        except Exception as exc:
            logger.warning("[SchemaStore] HTTP contract lookup failed: %s", exc)
            return None


class CompositeSchemaContractStore:
    def __init__(self, stores: Iterable[SchemaContractStore]):
        self.stores = [store for store in stores if store is not None]

    def get_contract(
        self,
        source_id: Optional[str],
        schema_version: Optional[str],
        schema_id: Optional[str] = None,
    ) -> Optional[SchemaContract]:
        for store in self.stores:
            contract = store.get_contract(source_id, schema_version, schema_id=schema_id)
            if contract:
                return contract
        return None


def build_schema_contract_store_from_env(clickhouse_client: Any = None) -> SchemaContractStore:
    """
    Build a composite schema contract store from environment configuration.

    Env:
    - SCHEMA_CONTRACT_STORE_ORDER=clickhouse,file,http (default)
    - SCHEMA_CONTRACT_CH_TABLE=schema_contract_registry
    - SCHEMA_CONTRACT_FILE_PATH=/var/lib/etl/schema_contracts.json
    - SCHEMA_CONTRACT_HTTP_ENDPOINT=http://metadata-service:8006/schema
    - SCHEMA_CONTRACT_HTTP_TIMEOUT=3.0
    """
    order_raw = os.getenv("SCHEMA_CONTRACT_STORE_ORDER", "clickhouse,file,http")
    backends = [item.strip().lower() for item in order_raw.split(",") if item.strip()]
    stores: List[SchemaContractStore] = []

    for backend in backends:
        if backend == "clickhouse" and clickhouse_client is not None:
            table_name = os.getenv("SCHEMA_CONTRACT_CH_TABLE", "schema_contract_registry")
            stores.append(ClickHouseSchemaContractStore(clickhouse_client, table_name=table_name))
        elif backend == "file":
            file_path = os.getenv("SCHEMA_CONTRACT_FILE_PATH")
            if file_path:
                stores.append(FileSchemaContractStore(file_path))
        elif backend == "http":
            endpoint = os.getenv("SCHEMA_CONTRACT_HTTP_ENDPOINT")
            if endpoint:
                timeout = float(os.getenv("SCHEMA_CONTRACT_HTTP_TIMEOUT", "3.0"))
                stores.append(HttpSchemaContractStore(endpoint, timeout_seconds=timeout))

    if not stores:
        return NullSchemaContractStore()
    if len(stores) == 1:
        return stores[0]
    return CompositeSchemaContractStore(stores)
