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


class _FakeType:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeResult:
    column_names = ["city", "sum_sales"]
    column_types = [_FakeType("LowCardinality(String)"), _FakeType("Nullable(Float64)")]
    result_rows = [("Damascus", 10.0), ("Aleppo", 12.0)]


class _FakeClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def query(self, sql: str):
        self.queries.append(sql)
        return _FakeResult()


def test_execute_query_returns_column_metadata_and_legacy_names():
    executor = ClickHouseExecutor.__new__(ClickHouseExecutor)
    executor.database = "etl"
    executor.client = _FakeClient()

    result = executor.execute_query(
        "SELECT city, SUM(sales) AS sum_sales FROM sales GROUP BY city",
        workspace_database="etl",
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
