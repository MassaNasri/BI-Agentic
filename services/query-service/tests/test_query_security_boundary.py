from __future__ import annotations

from contextlib import contextmanager
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, SERVICE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_config.settings")

import django  # noqa: E402

django.setup()

from query_api.application.query_execution import execute_sql_payload, validate_sql_payload  # noqa: E402
from query_api.services.workspace_concurrency import WorkspaceConcurrencyLimitExceeded  # noqa: E402
from query_api.services.workspace_db_resolver import WorkspaceDatasetBindingError  # noqa: E402


@contextmanager
def _lease(*_args, **_kwargs):
    yield


def _resolver(workspace_id, *, dataset_id=None, **_kwargs):
    pairs = {
        (1, 11): ("workspace_a", "table_a"),
        (2, 22): ("workspace_b", "table_b"),
    }
    if dataset_id in (None, "", b""):
        raise WorkspaceDatasetBindingError("dataset_id_required", "required", http_status=400)
    key = (int(workspace_id), int(dataset_id))
    if key not in pairs:
        raise WorkspaceDatasetBindingError("dataset_workspace_mismatch", "forbidden", http_status=403)
    database, table = pairs[key]
    return SimpleNamespace(
        workspace_id=int(workspace_id),
        dataset_id=int(dataset_id),
        clickhouse_db=database,
        table_name=table,
        allowed_tables=frozenset({table}),
    )


@pytest.mark.parametrize(
    "sql",
    (
        "SELECT * FROM table_b",
        "SELECT * FROM workspace_a.table_b",
        "SELECT * FROM table_a JOIN table_b ON table_a.id = table_b.id",
        "SELECT * FROM table_a WHERE id IN (SELECT id FROM table_b)",
        "WITH stolen AS (SELECT * FROM table_b) SELECT * FROM stolen",
        'SELECT * FROM "table_b"',
    ),
)
def test_workspace_a_cannot_bypass_dataset_a_allowlist(sql):
    with patch(
        "query_api.application.query_execution.resolve_workspace_dataset_binding",
        side_effect=_resolver,
    ):
        payload, status, _binding = validate_sql_payload(
            {"workspace_id": 1, "dataset_id": 11, "sql": sql}
        )

    assert status == 403
    assert payload["success"] is False
    assert payload["rows"] == []
    assert payload["error_code"] == "FORBIDDEN_DATASET"


def test_each_workspace_can_only_execute_its_own_dataset_and_returns_no_cross_data():
    executor = Mock()
    executor.execute_query.side_effect = lambda sql, **_kwargs: {
        "success": True,
        "rows": [{"source": "A" if "table_a" in sql else "B"}],
        "row_count": 1,
        "pagination": {"truncated": False},
    }
    with (
        patch(
            "query_api.application.query_execution.resolve_workspace_dataset_binding",
            side_effect=_resolver,
        ),
        patch(
            "query_api.application.query_execution.get_clickhouse_executor",
            return_value=executor,
        ),
    ):
        result_a, status_a = execute_sql_payload(
            {"workspace_id": 1, "dataset_id": 11, "sql": "SELECT * FROM table_a"},
            lease_factory=_lease,
        )
        result_b, status_b = execute_sql_payload(
            {"workspace_id": 2, "dataset_id": 22, "sql": "SELECT * FROM table_b"},
            lease_factory=_lease,
        )
        denied, denied_status = execute_sql_payload(
            {"workspace_id": 1, "dataset_id": 22, "sql": "SELECT * FROM table_b"},
            lease_factory=_lease,
        )

    assert (status_a, result_a["rows"]) == (200, [{"source": "A"}])
    assert (status_b, result_b["rows"]) == (200, [{"source": "B"}])
    assert denied_status == 403
    assert denied["rows"] == []
    assert executor.execute_query.call_count == 2


@pytest.mark.parametrize("dataset_id", (None, 999))
def test_missing_and_unknown_dataset_fail_before_executor(dataset_id):
    executor = Mock()
    with (
        patch(
            "query_api.application.query_execution.resolve_workspace_dataset_binding",
            side_effect=_resolver,
        ),
        patch(
            "query_api.application.query_execution.get_clickhouse_executor",
            return_value=executor,
        ),
    ):
        payload, http_status = execute_sql_payload(
            {"workspace_id": 1, "dataset_id": dataset_id, "sql": "SELECT * FROM table_a"},
            lease_factory=_lease,
        )
    assert http_status in {400, 403}
    assert payload["rows"] == []
    executor.execute_query.assert_not_called()


def test_client_physical_database_parameter_is_rejected_before_executor():
    executor = Mock()
    with patch(
        "query_api.application.query_execution.get_clickhouse_executor",
        return_value=executor,
    ):
        payload, http_status = execute_sql_payload(
            {
                "workspace_id": 1,
                "dataset_id": 11,
                "workspace_database": "workspace_b",
                "sql": "SELECT * FROM table_a",
            },
            lease_factory=_lease,
        )
    assert http_status == 400
    assert payload["rows"] == []
    executor.execute_query.assert_not_called()


def test_timeout_is_explicit_and_returns_no_data():
    executor = Mock()
    executor.execute_query.return_value = {
        "success": False,
        "error": "Query execution exceeded the authorized timeout.",
        "error_code": "QUERY_TIMEOUT",
        "aborted_due_to_timeout": True,
    }
    with (
        patch(
            "query_api.application.query_execution.resolve_workspace_dataset_binding",
            side_effect=_resolver,
        ),
        patch(
            "query_api.application.query_execution.get_clickhouse_executor",
            return_value=executor,
        ),
    ):
        payload, http_status = execute_sql_payload(
            {"workspace_id": 1, "dataset_id": 11, "sql": "SELECT * FROM table_a"},
            lease_factory=_lease,
        )
    assert http_status == 504
    assert payload["error_code"] == "QUERY_TIMEOUT"
    assert payload["rows"] == []


def test_concurrency_limit_fails_closed_before_clickhouse():
    executor = Mock()

    @contextmanager
    def at_capacity(*_args, **_kwargs):
        raise WorkspaceConcurrencyLimitExceeded("at capacity")
        yield

    with (
        patch(
            "query_api.application.query_execution.resolve_workspace_dataset_binding",
            side_effect=_resolver,
        ),
        patch(
            "query_api.application.query_execution.get_clickhouse_executor",
            return_value=executor,
        ),
    ):
        payload, http_status = execute_sql_payload(
            {"workspace_id": 1, "dataset_id": 11, "sql": "SELECT * FROM table_a"},
            lease_factory=at_capacity,
        )
    assert http_status == 429
    assert payload["error_code"] == "QUERY_LIMIT_EXCEEDED"
    assert payload["rows"] == []
    executor.execute_query.assert_not_called()
