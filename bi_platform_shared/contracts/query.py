"""Shared query-result metadata contracts.

These models describe the semantic shape of a query result at the service
boundary. Query-service emits them; visualization and voice-service can consume
them without re-guessing column types from sample values.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GenericColumnType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    DATE = "date"
    DATETIME = "datetime"
    BOOLEAN = "boolean"
    ARRAY = "array"
    UNKNOWN = "unknown"


class ColumnRole(str, Enum):
    TIME_FIELD = "time_field"
    CATEGORY_FIELD = "category_field"
    SERIES_FIELD = "series_field"
    METRIC_FIELD = "metric_field"
    UNKNOWN = "unknown"


class ColumnMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str
    clickhouse_type: Optional[str] = None
    generic_type: GenericColumnType = GenericColumnType.UNKNOWN
    role: ColumnRole = ColumnRole.UNKNOWN
    # Compatibility for existing code that expects column objects with "type".
    type: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_type(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        data = dict(values)
        if not data.get("clickhouse_type") and data.get("type"):
            data["clickhouse_type"] = data.get("type")
        if not data.get("type") and data.get("clickhouse_type"):
            data["type"] = data.get("clickhouse_type")
        generic = data.get("generic_type")
        if generic is None and data.get("clickhouse_type"):
            data["generic_type"] = map_clickhouse_type(str(data.get("clickhouse_type")))
        return data

    @model_validator(mode="after")
    def _sync_legacy_type(self) -> "ColumnMetadata":
        if self.type is None and self.clickhouse_type is not None:
            object.__setattr__(self, "type", self.clickhouse_type)
        if self.clickhouse_type is None and self.type is not None:
            object.__setattr__(self, "clickhouse_type", self.type)
        return self


class ResultShapeType(str, Enum):
    SINGLE_VALUE = "single_value"
    TIME_SERIES = "time_series"
    TIME_SERIES_GROUPED = "time_series_grouped"
    GROUPED = "grouped"
    MULTI_METRIC = "multi_metric"
    RAW = "raw"


class ResultShape(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: ResultShapeType
    time_field: Optional[str] = None
    category_fields: List[str] = Field(default_factory=list)
    series_fields: List[str] = Field(default_factory=list)
    metric_fields: List[str] = Field(default_factory=list)
    aggregation: Optional[str] = None
    sort: Optional[Dict[str, Any]] = None
    cardinality: Dict[str, int] = Field(default_factory=dict)
    row_count: int = 0


class QueryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    success: bool
    sql: str
    rows: List[Any] = Field(default_factory=list)
    columns: List[ColumnMetadata] = Field(default_factory=list)
    row_count: int = 0
    execution_time_ms: int = 0
    result_shape: Optional[ResultShape] = None
    column_names: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _populate_column_names(self) -> "QueryResponse":
        if not self.column_names and self.columns:
            object.__setattr__(self, "column_names", [column.name for column in self.columns])
        return self


_WRAPPER_PATTERN = re.compile(r"^(Nullable|LowCardinality)\((.*)\)$", flags=re.IGNORECASE)
_PARAM_PATTERN = re.compile(r"^([A-Za-z0-9_]+)\s*\(")


def unwrap_clickhouse_type(clickhouse_type: str | None) -> tuple[str, bool]:
    """Return the innermost type and whether an Array wrapper was present."""

    token = str(clickhouse_type or "").strip()
    if not token:
        return "", False

    saw_array = False
    previous = None
    while token and token != previous:
        previous = token
        if token.lower().startswith("array(") and token.endswith(")"):
            saw_array = True
            token = token[token.find("(") + 1 : -1].strip()
            continue
        match = _WRAPPER_PATTERN.match(token)
        if match:
            token = match.group(2).strip()
            continue
    return token, saw_array


def map_clickhouse_type(clickhouse_type: str | None) -> GenericColumnType:
    """Map a ClickHouse native type to a stable generic type."""

    inner, saw_array = unwrap_clickhouse_type(clickhouse_type)
    if saw_array:
        return GenericColumnType.ARRAY
    if not inner:
        return GenericColumnType.UNKNOWN

    base_match = _PARAM_PATTERN.match(inner)
    base = (base_match.group(1) if base_match else inner).strip().lower()

    if base in {"date", "date32"}:
        return GenericColumnType.DATE
    if base in {"datetime", "datetime64"}:
        return GenericColumnType.DATETIME
    if base in {"string", "fixedstring"} or base.startswith("enum"):
        return GenericColumnType.STRING
    if base in {"bool", "boolean"}:
        return GenericColumnType.BOOLEAN
    if re.match(r"^u?int(8|16|32|64|128|256)$", base):
        return GenericColumnType.NUMBER
    if base in {"float32", "float64", "float", "double"}:
        return GenericColumnType.NUMBER
    if re.match(r"^decimal(32|64|128|256)?$", base):
        return GenericColumnType.NUMBER
    return GenericColumnType.UNKNOWN


def build_column_metadata(
    column_names: list[str],
    column_types: list[str] | None = None,
) -> list[ColumnMetadata]:
    """Zip ClickHouse names/types into metadata while tolerating missing types."""

    types = list(column_types or [])
    metadata: list[ColumnMetadata] = []
    for index, name in enumerate(column_names):
        clickhouse_type = str(types[index]).strip() if index < len(types) else None
        metadata.append(
            ColumnMetadata(
                name=str(name),
                clickhouse_type=clickhouse_type,
                generic_type=map_clickhouse_type(clickhouse_type),
            )
        )
    return metadata


__all__ = [
    "ColumnMetadata",
    "ColumnRole",
    "GenericColumnType",
    "QueryResponse",
    "ResultShape",
    "ResultShapeType",
    "build_column_metadata",
    "map_clickhouse_type",
    "unwrap_clickhouse_type",
]
