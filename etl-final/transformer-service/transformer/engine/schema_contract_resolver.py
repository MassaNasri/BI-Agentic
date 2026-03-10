"""
Schema contract resolver for transformer Kafka flow.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from shared.models import SchemaContract, SchemaValidator
from shared.utils.schema_contract_store import SchemaContractStore, NullSchemaContractStore


logger = logging.getLogger(__name__)


class SchemaContractResolver:
    """
    Resolves schema contracts for incoming transformer messages.

    Resolution order:
    1) Inline message schema_contract
    2) Registry lookup by (source_id, schema_version)
    3) Registry lookup by (schema_id, schema_version)
    """

    def __init__(
        self,
        schema_validator: SchemaValidator,
        contract_store: Optional[SchemaContractStore] = None,
    ):
        self.schema_validator = schema_validator
        self.contract_store = contract_store or NullSchemaContractStore()
        self._source_registry: Dict[Tuple[str, str], SchemaContract] = {}
        self._schema_registry: Dict[Tuple[str, str], SchemaContract] = {}

    def _coerce_contract(self, schema_contract: Any) -> Optional[SchemaContract]:
        if schema_contract is None:
            return None
        if isinstance(schema_contract, SchemaContract):
            self.schema_validator.cache_schema(schema_contract)
            return schema_contract
        if isinstance(schema_contract, dict):
            try:
                schema_id = schema_contract.get("schema_id")
                version = schema_contract.get("version")
                if schema_id and version:
                    cached = self.schema_validator.get_cached_schema(schema_id, version)
                    if cached:
                        return cached
                contract = SchemaContract.from_dict(schema_contract)
                self.schema_validator.cache_schema(contract)
                return contract
            except Exception as exc:
                logger.warning("Failed to parse schema contract from dict: %s", exc)
                return None
        return None

    def register(
        self,
        source_id: Optional[str],
        schema_version: Optional[str],
        schema_contract: Any,
    ) -> Optional[SchemaContract]:
        contract = self._coerce_contract(schema_contract)
        if contract is None:
            return None

        if source_id and schema_version:
            self._source_registry[(str(source_id), str(schema_version))] = contract
        if contract.schema_id and contract.version:
            self._schema_registry[(contract.schema_id, contract.version)] = contract
        return contract

    def resolve_for_message(
        self,
        message: Dict[str, Any],
        fallback_contract: Optional[SchemaContract] = None,
    ) -> Optional[SchemaContract]:
        source_id = message.get("source")
        if not source_id:
            source_id = message.get("source_id")
        schema_version = message.get("schema_version")
        inline_contract = message.get("schema_contract")

        if inline_contract is not None:
            contract = self.register(source_id, schema_version, inline_contract)
            if contract:
                return contract

        if source_id and schema_version:
            source_match = self._source_registry.get((str(source_id), str(schema_version)))
            if source_match:
                return source_match

        schema_id = message.get("schema_id")
        if schema_id and schema_version:
            schema_match = self._schema_registry.get((str(schema_id), str(schema_version)))
            if schema_match:
                return schema_match

        persisted = self.contract_store.get_contract(
            source_id=str(source_id) if source_id else None,
            schema_version=str(schema_version) if schema_version else None,
            schema_id=str(schema_id) if schema_id else None,
        )
        if persisted:
            self.register(source_id, schema_version, persisted)
            return persisted

        return fallback_contract
