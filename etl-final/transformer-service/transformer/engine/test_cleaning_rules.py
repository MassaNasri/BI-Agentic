from unittest.mock import Mock, patch

from .cleaning_rules import CleaningRules
from .transformer_service import TransformerService


def test_boolean_coercion_unknown_string_is_not_forced_true():
    rules = CleaningRules()
    row = {"flag": "nope"}
    cleaned = rules.coerce_types(row, schema={"flag": "boolean"})
    assert cleaned["flag"] == "nope"


def test_infer_type_preserves_leading_zero_identifiers():
    rules = CleaningRules()
    row = {"code": "007"}
    cleaned = rules.coerce_types(row)
    assert cleaned["code"] == "007"


def test_transformer_service_does_not_require_schema_contract_by_default():
    service = TransformerService(quarantine_manager=Mock(), default_rules=[])
    results, stats = service.process_batch(
        [{"source": "src", "batch_id": "b1", "data": {"id": 1}}],
        rules=[],
        schema_contract=None,
    )
    assert stats["failed"] == 0
    assert stats["success"] == 1
    assert results[0]["status"] == "success"


def test_transformer_service_can_require_schema_contract_via_env():
    with patch.dict("os.environ", {"TRANSFORMER_REQUIRE_SCHEMA_CONTRACT": "true"}, clear=False):
        service = TransformerService(quarantine_manager=Mock(), default_rules=[])
        results, stats = service.process_batch(
            [{"source": "src", "batch_id": "b1", "schema_version": "1.0.0", "data": {"id": 1}}],
            rules=[],
            schema_contract=None,
        )
    assert stats["failed"] == 1
    assert results[0]["status"] == "failed"
    assert any("Missing schema contract" in w for w in results[0]["warnings"])


def test_transformer_schema_contract_warn_mode_processes_and_tags_rows():
    with patch.dict("os.environ", {"SCHEMA_CONTRACT_MODE": "warn"}, clear=False):
        service = TransformerService(quarantine_manager=Mock(), default_rules=[])
        results, stats = service.process_batch(
            [{"source": "src", "batch_id": "b1", "schema_version": "1.0.0", "data": {"id": 1}}],
            rules=[],
            schema_contract=None,
        )

    assert stats["failed"] == 0
    assert stats["schema_contract_missing"] == 1
    assert results[0]["status"] == "success"
    assert results[0]["clean_message"]["_schema_contract_missing"] is True
    assert results[0]["clean_message"]["_schema_contract_mode"] == "warn"
