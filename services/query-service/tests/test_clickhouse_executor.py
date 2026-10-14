from __future__ import annotations

import sys
from pathlib import Path

def _resolve_repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in (current.parent, *current.parents):
        if (candidate / "bi_platform_shared").is_dir():
            return candidate
    raise RuntimeError("Could not locate repository root containing bi_platform_shared")


REPO_ROOT = _resolve_repo_root()
SERVICE_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, SERVICE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from query_api.services.clickhouse_executor import ClickHouseExecutor  # noqa: E402
from query_api.resource_policy import QueryResourcePolicy  # noqa: E402


class _FakeType:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeResult:
    column_names = ["city", "sum_sales"]
    column_types = [_FakeType("LowCardinality(String)"), _FakeType("Nullable(Float64)")]
    result_rows = [("Damascus", 10.0), ("Aleppo", 12.0)]
    summary = {"read_rows": "20", "read_bytes": "500"}


class _FakeClient:
    def __init__(self, *, active_queries: int = 1) -> None:
        self.queries: list[str] = []
        self.active_queries = active_queries

    def query(self, sql: str, **kwargs):
        self.queries.append(sql)
        self.kwargs = kwargs
        if "system.processes" in sql:
            result = _FakeResult()
            result.result_rows = [(self.active_queries,)]
            return result
        return _FakeResult()

    def command(self, sql: str, **kwargs):
        self.command_sql = sql
        self.command_kwargs = kwargs
        return "finished"


def _policy(**overrides):
    values = {
        "max_execution_seconds": 10,
        "max_rows": 100,
        "max_result_bytes": 100_000,
        "max_bytes_to_read": 1_000_000,
        "max_memory_usage": 1_000_000,
        "workspace_concurrency": 2,
        "default_page_size": 20,
        "max_page_size": 50,
    }
    values.update(overrides)
    return QueryResourcePolicy(**values)


def test_execute_query_returns_column_metadata_and_legacy_names():
    executor = ClickHouseExecutor.__new__(ClickHouseExecutor)
    executor.database = "etl"
    executor.client = _FakeClient()

    result = executor.execute_query(
        "SELECT city, SUM(sales) AS sum_sales FROM sales GROUP BY city",
        workspace_database="etl",
        policy=_policy(),
        query_id="biavora-w1-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )

    assert result["success"] is True
    assert result["column_names"] == ["city", "sum_sales"]
    assert result["column_types"] == ["LowCardinality(String)", "Nullable(Float64)"]
    assert result["columns"][0]["name"] == "city"
    assert result["columns"][0]["generic_type"] == "string"
    assert result["columns"][0]["role"] == "category_field"
    assert result["columns"][1]["generic_type"] == "number"
    assert result["columns"][1]["role"] == "metric_field"
    assert result["result_shape"]["type"] == "grouped"
    assert result["scanned_rows"] == 20
    assert result["bytes_read"] == 500
    assert executor.client.kwargs["settings"]["readonly"] == 1
    assert executor.client.kwargs["settings"]["max_execution_time"] == 10
    assert executor.client.kwargs["settings"]["query_id"].startswith("biavora-w1-")
    assert "LIMIT 21 OFFSET 0" in executor.client.queries[0]


def test_execute_query_returns_explicit_truncation_and_next_page():
    executor = ClickHouseExecutor.__new__(ClickHouseExecutor)
    executor.database = "etl"
    executor.client = _FakeClient()

    result = executor.execute_query(
        "SELECT city, sales FROM sales",
        workspace_database="etl",
        policy=_policy(default_page_size=1),
    )

    assert result["success"] is True
    assert result["row_count"] == 1
    assert result["pagination"] == {
        "page": 1,
        "page_size": 1,
        "returned_count": 1,
        "truncated": True,
        "next_page": 2,
        "limit_reached": False,
        "max_rows": 100,
    }


def test_execute_query_rejects_response_over_authoritative_byte_limit():
    executor = ClickHouseExecutor.__new__(ClickHouseExecutor)
    executor.database = "etl"
    executor.client = _FakeClient()

    result = executor.execute_query(
        "SELECT city, sales FROM sales",
        workspace_database="etl",
        policy=_policy(max_result_bytes=2),
    )

    assert result["success"] is False
    assert result["error_code"] == "QUERY_LIMIT_EXCEEDED"
    assert "rows" not in result


def test_cancel_query_uses_validated_workspace_scoped_query_id():
    executor = ClickHouseExecutor.__new__(ClickHouseExecutor)
    executor.database = "etl"
    executor.client = _FakeClient()
    query_id = "biavora-w7-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

    result = executor.cancel_query(query_id)

    assert result == {"success": True, "cancelled": True, "query_id": query_id}
    assert "system.processes" in executor.client.queries[0]
    assert "%(query_id)s" in executor.client.command_sql
    assert executor.client.command_kwargs["parameters"] == {"query_id": query_id}


def test_cancel_query_reports_when_scoped_query_is_not_running():
    executor = ClickHouseExecutor.__new__(ClickHouseExecutor)
    executor.database = "etl"
    executor.client = _FakeClient(active_queries=0)
    query_id = "biavora-w7-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

    result = executor.cancel_query(query_id)

    assert result == {"success": True, "cancelled": False, "query_id": query_id}
    assert not hasattr(executor.client, "command_sql")


class _RaisingClient:
    def __init__(self, message: str) -> None:
        self.message = message

    def query(self, sql: str, **kwargs):
        raise RuntimeError(self.message)


def test_clickhouse_26_result_limit_error_is_safely_typed():
    executor = ClickHouseExecutor.__new__(ClickHouseExecutor)
    executor.database = "etl"
    executor.client = _RaisingClient(
        "Limit for result exceeded. (TOO_MANY_ROWS_OR_BYTES)"
    )

    result = executor.execute_query(
        "SELECT city FROM sales",
        workspace_database="etl",
        policy=_policy(),
    )

    assert result["success"] is False
    assert result["error_code"] == "QUERY_LIMIT_EXCEEDED"
    assert result["error"] == "Query execution exceeded an authorized resource limit."


def test_clickhouse_26_bytes_read_error_is_safely_typed():
    executor = ClickHouseExecutor.__new__(ClickHouseExecutor)
    executor.database = "etl"
    executor.client = _RaisingClient(
        "Limit for rows or bytes to read exceeded. (TOO_MANY_BYTES)"
    )

    result = executor.execute_query(
        "SELECT city FROM sales",
        workspace_database="etl",
        policy=_policy(),
    )

    assert result["success"] is False
    assert result["error_code"] == "QUERY_LIMIT_EXCEEDED"


def test_cancel_query_rejects_untrusted_query_identifier():
    executor = ClickHouseExecutor.__new__(ClickHouseExecutor)
    executor.database = "etl"
    executor.client = _FakeClient()

    result = executor.cancel_query("x' OR 1=1 --")

    assert result["success"] is False
    assert result["error_code"] == "VALIDATION_REJECTED"
    assert not hasattr(executor.client, "command_sql")
