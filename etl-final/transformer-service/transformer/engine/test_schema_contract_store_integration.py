from unittest.mock import Mock, patch

from shared.models import SchemaContract

from .transformer_service import TransformerService


def _contract_dict(version: str = "1.0.0"):
    return {
        "schema_id": "users_schema",
        "version": version,
        "fields": [
            {"name": "id", "type": "integer", "nullable": False},
            {"name": "name", "type": "string", "nullable": True},
        ],
    }


class _Store:
    def __init__(self):
        self.calls = []

    def get_contract(self, source_id, schema_version, schema_id=None):
        self.calls.append((source_id, schema_version, schema_id))
        if source_id == "users" and schema_version == "1.0.0":
            return SchemaContract.from_dict(_contract_dict("1.0.0"))
        return None


def test_resolver_loads_contract_from_persistent_store_by_source_and_version():
    store = _Store()
    with patch.dict("os.environ", {"SCHEMA_CONTRACT_MODE": "strict"}, clear=False):
        service = TransformerService(
            quarantine_manager=Mock(),
            default_rules=[],
            schema_contract_store=store,
        )
        results, stats = service.process_batch(
            [
                {
                    "source": "users",
                    "source_id": "users",
                    "batch_id": "b1",
                    "schema_version": "1.0.0",
                    "data": {"id": 1, "name": "Alice"},
                }
            ],
            rules=[],
            schema_contract=None,
        )

    assert stats["failed"] == 0
    assert stats["success"] == 1
    assert stats["schema_contract_missing"] == 0
    assert results[0]["status"] == "success"
    assert results[0]["clean_message"]["_schema_contract_missing"] is False
    assert results[0]["clean_message"]["validation_score"] is not None
    assert store.calls
