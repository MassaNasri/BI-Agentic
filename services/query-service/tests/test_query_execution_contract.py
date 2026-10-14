from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from query_api.application.query_execution import execute_sql_payload


@contextmanager
def _lease(*_args, **_kwargs):
    yield


def _binding():
    return SimpleNamespace(
        workspace_id=1,
        dataset_id=7,
        clickhouse_db="workspace_test",
        table_name="sales",
        allowed_tables=frozenset({"sales"}),
    )


def test_execute_sql_payload_includes_success_true():
    executor = SimpleNamespace(
        execute_query=lambda *_args, **_kwargs: {
            "success": True,
            "rows": [{"total": 3}],
            "columns": [{"name": "total", "type": "UInt64"}],
            "column_names": ["total"],
            "column_types": ["UInt64"],
            "row_count": 1,
            "execution_time_ms": 7,
        }
    )
    with (
        patch(
            "query_api.application.query_execution.resolve_workspace_dataset_binding",
            return_value=_binding(),
        ),
        patch(
            "query_api.application.query_execution.get_clickhouse_executor",
            return_value=executor,
        ),
    ):
        payload, http_status = execute_sql_payload(
            {
                "workspace_id": 1,
                "dataset_id": 7,
                "sql": "SELECT count() AS total FROM sales",
                "request_id": "test-request",
            },
            lease_factory=_lease,
        )

    assert http_status == 200
    assert payload["success"] is True
    assert payload["status"] == "success"
    assert payload["dataset_id"] == 7


def test_execute_sql_payload_includes_success_false():
    with (
        patch(
            "query_api.application.query_execution.resolve_workspace_dataset_binding",
            return_value=_binding(),
        ),
    ):
        payload, http_status = execute_sql_payload(
            {"workspace_id": 1, "dataset_id": 7, "sql": "DELETE FROM sales"},
            lease_factory=_lease,
        )

    assert http_status == 400
    assert payload["success"] is False
    assert payload["status"] == "failed"
    assert payload["error_code"] == "VALIDATION_REJECTED"
