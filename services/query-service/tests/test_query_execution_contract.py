from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from query_api.application.query_execution import execute_sql_payload


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
    resolution = SimpleNamespace(clickhouse_db="workspace_test")

    with (
        patch(
            "query_api.application.query_execution.resolve_workspace_clickhouse_db",
            return_value=resolution,
        ),
        patch(
            "query_api.application.query_execution.SQLGuard.validate_and_sanitize",
            return_value=(True, "", "SELECT count() AS total"),
        ),
        patch(
            "query_api.application.query_execution.get_clickhouse_executor",
            return_value=executor,
        ),
    ):
        payload, http_status = execute_sql_payload(
            {"workspace_id": 1, "sql": "SELECT count() AS total"}
        )

    assert http_status == 200
    assert payload["success"] is True
    assert payload["status"] == "success"


def test_execute_sql_payload_includes_success_false():
    resolution = SimpleNamespace(clickhouse_db="workspace_test")

    with (
        patch(
            "query_api.application.query_execution.resolve_workspace_clickhouse_db",
            return_value=resolution,
        ),
        patch(
            "query_api.application.query_execution.SQLGuard.validate_and_sanitize",
            return_value=(False, "Only SELECT queries are allowed", "DELETE FROM sales"),
        ),
    ):
        payload, http_status = execute_sql_payload(
            {"workspace_id": 1, "sql": "DELETE FROM sales"}
        )

    assert http_status == 400
    assert payload["success"] is False
    assert payload["status"] == "failed"
    assert payload["error"]
