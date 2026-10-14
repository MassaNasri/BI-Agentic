from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _resolve_repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in (current.parent, *current.parents):
        if (candidate / "bi_platform_shared").is_dir():
            return candidate
    raise RuntimeError("Could not locate repository root containing bi_platform_shared")


REPO_ROOT = _resolve_repo_root()
SERVICE_ROOT = REPO_ROOT / "services" / "query-service"
for path in (REPO_ROOT, SERVICE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from query_api.services.workspace_db_resolver import (  # noqa: E402
    WorkspaceDatasetBindingError,
    resolve_workspace_dataset_binding,
)


class _FakeQuerySet:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value

    def order_by(self, *_args):
        return self


class _FakeManager:
    def __init__(self, records):
        self.records = list(records)

    def filter(self, **kwargs):
        matches = self.records
        for key, value in kwargs.items():
            matches = [
                record
                for record in matches
                if getattr(record, "pk" if key == "pk" else key) == value
            ]
        return _FakeQuerySet(matches[0] if matches else None)


def _database_model(*records):
    return SimpleNamespace(objects=_FakeManager(records))


def _record(**overrides):
    values = {
        "pk": 4,
        "workspace_id": 3,
        "manager": 4,
        "clickhouse_database": "etl",
        "clickhouse_table_name": "sales",
        "source_tables": [],
        "etl_status": "completed",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_valid_binding_checks_physical_table():
    binding = resolve_workspace_dataset_binding(
        3,
        database_model=_database_model(_record()),
        table_exists=lambda database, table: {
            "success": database == "etl" and table == "sales",
            "exists": True,
        },
    )

    assert binding.dataset_id == 4
    assert binding.workspace_id == 3
    assert binding.table_name == "sales"
    assert binding.allowed_tables == frozenset({"sales"})


def test_required_logical_dataset_id_fails_closed():
    with pytest.raises(WorkspaceDatasetBindingError) as raised:
        resolve_workspace_dataset_binding(
            3,
            require_dataset_id=True,
            database_model=_database_model(_record()),
        )

    assert raised.value.code == "dataset_id_required"


def test_multi_table_dataset_produces_exact_non_empty_allowlist():
    binding = resolve_workspace_dataset_binding(
        3,
        dataset_id=4,
        verify_physical=False,
        require_dataset_id=True,
        database_model=_database_model(
            _record(
                source_tables=[
                    {"destination_table": "sales", "status": "completed"},
                    {"destination_table": "customers", "status": "completed"},
                    {"destination_table": "ignored", "status": "failed"},
                ]
            )
        ),
    )

    assert binding.allowed_tables == frozenset({"sales", "customers"})


def test_missing_workspace_binding_is_structured_422():
    with pytest.raises(WorkspaceDatasetBindingError) as raised:
        resolve_workspace_dataset_binding(2, database_model=_database_model())

    assert raised.value.code == "dataset_metadata_missing"
    assert raised.value.http_status == 422


def test_stale_explicit_dataset_is_rejected():
    with pytest.raises(WorkspaceDatasetBindingError) as raised:
        resolve_workspace_dataset_binding(
            3,
            dataset_id=999,
            database_model=_database_model(_record()),
        )

    assert raised.value.code == "dataset_metadata_stale"


def test_cross_workspace_dataset_is_forbidden():
    with pytest.raises(WorkspaceDatasetBindingError) as raised:
        resolve_workspace_dataset_binding(
            2,
            dataset_id=4,
            database_model=_database_model(_record()),
        )

    assert raised.value.code == "dataset_workspace_mismatch"
    assert raised.value.http_status == 403


def test_missing_physical_table_is_rejected():
    with pytest.raises(WorkspaceDatasetBindingError) as raised:
        resolve_workspace_dataset_binding(
            3,
            database_model=_database_model(_record()),
            table_exists=lambda _database, _table: {"success": True, "exists": False},
        )

    assert raised.value.code == "dataset_physical_table_missing"


def test_explicit_table_must_match_metadata():
    with pytest.raises(WorkspaceDatasetBindingError) as raised:
        resolve_workspace_dataset_binding(
            3,
            table_name="other_table",
            database_model=_database_model(_record()),
            verify_physical=False,
        )

    assert raised.value.code == "dataset_table_mismatch"


@pytest.mark.parametrize("etl_status", ("failed", "deleted", "inactive", ""))
def test_inactive_or_failed_dataset_is_rejected(etl_status):
    with pytest.raises(WorkspaceDatasetBindingError) as raised:
        resolve_workspace_dataset_binding(
            3,
            dataset_id=4,
            require_dataset_id=True,
            verify_physical=False,
            database_model=_database_model(_record(etl_status=etl_status)),
        )

    assert raised.value.code == "dataset_metadata_invalid"


def test_empty_dataset_binding_is_rejected():
    with pytest.raises(WorkspaceDatasetBindingError) as raised:
        resolve_workspace_dataset_binding(
            3,
            dataset_id=4,
            require_dataset_id=True,
            verify_physical=False,
            database_model=_database_model(
                _record(clickhouse_table_name="", source_tables=[])
            ),
        )

    assert raised.value.code == "dataset_metadata_invalid"
