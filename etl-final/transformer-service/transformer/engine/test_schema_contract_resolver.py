from unittest.mock import Mock, patch

from .transformer_service import TransformerService


def _schema_contract_dict(version: str = "1.0.0"):
    return {
        "schema_id": "users_schema",
        "version": version,
        "fields": [
            {"name": "id", "type": "integer", "nullable": False},
            {"name": "name", "type": "string", "nullable": True},
        ],
    }


def test_registered_contract_is_reused_by_source_and_schema_version():
    quarantine_manager = Mock()
    with patch.dict("os.environ", {"TRANSFORMER_REQUIRE_SCHEMA_CONTRACT": "true"}, clear=False):
        service = TransformerService(quarantine_manager=quarantine_manager, default_rules=[])
        results, stats = service.process_batch(
            [
                {
                    "source": "users",
                    "batch_id": "b1",
                    "schema_version": "1.0.0",
                    "data": {"id": 1, "name": "Alice"},
                    "schema_contract": _schema_contract_dict("1.0.0"),
                },
                {
                    "source": "users",
                    "batch_id": "b1",
                    "schema_version": "1.0.0",
                    "data": {"id": 2, "name": "Bob"},
                },
            ],
            rules=[],
            schema_contract=None,
        )
    assert stats["failed"] == 0
    assert stats["success"] == 2
    assert stats["quarantined"] == 0
    assert all(result["status"] == "success" for result in results)
    quarantine_manager.quarantine.assert_not_called()


def test_missing_registered_contract_fails_when_required():
    quarantine_manager = Mock()
    with patch.dict("os.environ", {"TRANSFORMER_REQUIRE_SCHEMA_CONTRACT": "true"}, clear=False):
        service = TransformerService(quarantine_manager=quarantine_manager, default_rules=[])
        results, stats = service.process_batch(
            [
                {
                    "source": "users",
                    "batch_id": "b1",
                    "schema_version": "9.9.9",
                    "data": {"id": 1},
                }
            ],
            rules=[],
            schema_contract=None,
        )
    assert stats["failed"] == 1
    assert stats["quarantined"] == 1
    assert results[0]["status"] == "failed"

