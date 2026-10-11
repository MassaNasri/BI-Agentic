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

from bi_platform_shared.contracts.query import (  # noqa: E402
    ColumnMetadata,
    ColumnRole,
    GenericColumnType,
    build_column_metadata,
)
from query_api.services.result_shape_analyzer import analyze_result_shape  # noqa: E402


def _columns(*specs: tuple[str, str]) -> list[ColumnMetadata]:
    return build_column_metadata(
        [name for name, _ in specs],
        [clickhouse_type for _, clickhouse_type in specs],
    )


def test_single_aggregate_result():
    columns = _columns(("count", "UInt64"))
    shape = analyze_result_shape("SELECT count() AS count FROM t", columns, [{"count": 42}])

    assert shape.type == "single_value"
    assert shape.metric_fields == ["count"]
    assert columns[0].role == ColumnRole.METRIC_FIELD


def test_date_one_metric_time_series_with_sort():
    columns = _columns(("period", "Date"), ("sum_sales", "Float64"))
    shape = analyze_result_shape(
        "SELECT period, SUM(sales) AS sum_sales FROM t GROUP BY period ORDER BY period DESC",
        columns,
        [{"period": "2026-01-01", "sum_sales": 10.0}, {"period": "2026-01-02", "sum_sales": 12.0}],
    )

    assert shape.type == "time_series"
    assert shape.time_field == "period"
    assert shape.metric_fields == ["sum_sales"]
    assert shape.sort == {"column": "period", "direction": "DESC"}
    assert columns[0].role == ColumnRole.TIME_FIELD


def test_date_series_metric_time_series_grouped():
    columns = _columns(("period", "DateTime"), ("city", "LowCardinality(String)"), ("sum_sales", "Decimal(18, 2)"))
    shape = analyze_result_shape(
        "SELECT period, city, SUM(sales) AS sum_sales FROM t GROUP BY period, city",
        columns,
        [
            {"period": "2026-01-01", "city": "Damascus", "sum_sales": 10.0},
            {"period": "2026-01-01", "city": "Aleppo", "sum_sales": 12.0},
        ],
    )

    assert shape.type == "time_series_grouped"
    assert shape.series_fields == ["city"]
    assert shape.cardinality == {"city": 2}
    assert columns[1].role == ColumnRole.SERIES_FIELD


def test_category_one_metric_grouped():
    columns = _columns(("city", "String"), ("sum_sales", "Float64"))
    shape = analyze_result_shape(
        "SELECT city, SUM(sales) AS sum_sales FROM t GROUP BY city",
        columns,
        [{"city": "Damascus", "sum_sales": 10.0}, {"city": "Aleppo", "sum_sales": 12.0}],
    )

    assert shape.type == "grouped"
    assert shape.category_fields == ["city"]
    assert shape.metric_fields == ["sum_sales"]


def test_category_two_metrics_multi_metric():
    columns = _columns(("category", "String"), ("revenue", "Float64"), ("profit", "Float64"))
    shape = analyze_result_shape(
        "SELECT category, SUM(revenue) AS revenue, SUM(profit) AS profit FROM t GROUP BY category",
        columns,
        [{"category": "A", "revenue": 10.0, "profit": 2.0}],
    )

    assert shape.type == "multi_metric"
    assert shape.metric_fields == ["revenue", "profit"]


def test_raw_mixed_result_with_no_metric():
    columns = _columns(("event_time", "String"), ("payload", "JSON"))
    shape = analyze_result_shape(
        "SELECT event_time, payload FROM raw_events",
        columns,
        [{"event_time": "today", "payload": "{}"}],
    )

    assert shape.type == "raw"
    assert shape.metric_fields == []


def test_empty_result_is_safe_and_keeps_shape_metadata():
    columns = _columns(("period", "Nullable(Date)"), ("sum_sales", "Nullable(Float64)"))
    shape = analyze_result_shape(
        "SELECT period, SUM(sales) AS sum_sales FROM t GROUP BY period",
        columns,
        [],
    )

    assert shape.row_count == 0
    assert shape.type == "time_series"
    assert shape.metric_fields == ["sum_sales"]


def test_unknown_category_and_high_cardinality_are_reported():
    columns = [
        ColumnMetadata(name="segment", clickhouse_type="CustomType", generic_type=GenericColumnType.UNKNOWN),
        ColumnMetadata(name="total", clickhouse_type="UInt64", generic_type=GenericColumnType.NUMBER),
    ]
    rows = [{"segment": f"S{i}", "total": i} for i in range(30)]
    shape = analyze_result_shape(
        "SELECT segment, SUM(total) AS total FROM t GROUP BY segment",
        columns,
        rows,
    )

    assert shape.type == "grouped"
    assert shape.cardinality == {"segment": 30}
