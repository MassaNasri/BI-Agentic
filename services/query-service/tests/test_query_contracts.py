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
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bi_platform_shared.contracts.query import (  # noqa: E402
    ColumnMetadata,
    GenericColumnType,
    QueryResponse,
    ResultShape,
    ResultShapeType,
    build_column_metadata,
    map_clickhouse_type,
)


def test_clickhouse_type_mapping_core_wrappers():
    assert map_clickhouse_type("Date") == GenericColumnType.DATE
    assert map_clickhouse_type("DateTime64(3)") == GenericColumnType.DATETIME
    assert map_clickhouse_type("Nullable(Int64)") == GenericColumnType.NUMBER
    assert map_clickhouse_type("LowCardinality(String)") == GenericColumnType.STRING
    assert map_clickhouse_type("Nullable(LowCardinality(String))") == GenericColumnType.STRING
    assert map_clickhouse_type("Decimal(18, 2)") == GenericColumnType.NUMBER
    assert map_clickhouse_type("Decimal256(8)") == GenericColumnType.NUMBER
    assert map_clickhouse_type("Array(String)") == GenericColumnType.ARRAY
    assert map_clickhouse_type("AggregateFunction(sum, UInt64)") == GenericColumnType.UNKNOWN


def test_build_column_metadata_tolerates_missing_types():
    columns = build_column_metadata(["day", "sales", "notes"], ["Date", "Nullable(Float64)"])

    assert [column.name for column in columns] == ["day", "sales", "notes"]
    assert columns[0].clickhouse_type == "Date"
    assert columns[0].generic_type == GenericColumnType.DATE
    assert columns[1].generic_type == GenericColumnType.NUMBER
    assert columns[2].generic_type == GenericColumnType.UNKNOWN


def test_query_response_serializes_metadata_and_legacy_column_names():
    response = QueryResponse(
        success=True,
        sql="SELECT count() AS total",
        rows=[{"total": 3}],
        columns=[
            ColumnMetadata(
                name="total",
                clickhouse_type="UInt64",
                generic_type=GenericColumnType.NUMBER,
            )
        ],
        row_count=1,
        execution_time_ms=7,
        result_shape=ResultShape(
            type=ResultShapeType.SINGLE_VALUE,
            metric_fields=["total"],
            row_count=1,
        ),
    )

    payload = response.model_dump(mode="json")

    assert payload["column_names"] == ["total"]
    assert payload["columns"] == [
        {
            "name": "total",
            "clickhouse_type": "UInt64",
            "generic_type": "number",
            "role": "unknown",
            "type": "UInt64",
        }
    ]
    assert payload["result_shape"]["type"] == "single_value"
