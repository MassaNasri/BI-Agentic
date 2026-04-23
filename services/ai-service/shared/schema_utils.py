import re
from typing import Any

from shared.pipeline_guards import is_technical_column_name


NUMERIC_TYPE_TOKENS = (
    "int",
    "float",
    "decimal",
    "numeric",
    "double",
    "real",
    "money",
)
DATE_TYPE_TOKENS = ("date", "datetime", "timestamp", "time")


def tokenize(text: str) -> set[str]:
    if not text:
        return set()
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def normalize_column_type(col_type: str) -> str:
    if not col_type:
        return ""
    normalized = col_type.strip().lower()
    normalized = normalized.replace("nullable(", "").replace("lowcardinality(", "")
    normalized = normalized.replace(")", "")
    return normalized


def is_numeric_type(col_type: str) -> bool:
    normalized = normalize_column_type(col_type)
    return any(token in normalized for token in NUMERIC_TYPE_TOKENS)


def is_date_type(col_type: str) -> bool:
    normalized = normalize_column_type(col_type)
    return any(token in normalized for token in DATE_TYPE_TOKENS)


def is_dimension_type(col_type: str) -> bool:
    return not is_numeric_type(col_type) and not is_date_type(col_type)


def build_table_metadata(columns: list[dict[str, Any]]) -> dict[str, Any]:
    column_map = {col["name"]: col for col in columns}
    business_columns = [c for c in columns if not is_technical_column_name(str(c.get("name", "")))]
    numeric_columns = [c["name"] for c in business_columns if c.get("is_numeric")]
    date_columns = [c["name"] for c in business_columns if c.get("is_date")]
    dimension_columns = [c["name"] for c in business_columns if c.get("is_dimension")]
    technical_columns = [c["name"] for c in columns if is_technical_column_name(str(c.get("name", "")))]
    return {
        "columns": columns,
        "column_map": column_map,
        "numeric_columns": numeric_columns,
        "date_columns": date_columns,
        "dimension_columns": dimension_columns,
        "technical_columns": technical_columns,
    }


def _split_table_parts(table_name: str) -> list[str]:
    if not table_name or not table_name.strip():
        return []
    return [part.strip() for part in table_name.split(".") if part and part.strip()]


def normalize_table_name(table_name: str, default_db: str) -> str:
    """
    Normalize table names to ClickHouse-safe `database.table` form.

    Rules:
    - `table` -> `default_db.table`
    - `db.table` -> `db.table`
    - `db.db.table` -> `db.table` (defensive duplicate-db repair)
    """
    if not default_db or not default_db.strip():
        raise ValueError("default_db must be a non-empty string")

    parts = _split_table_parts(table_name)
    if not parts:
        raise ValueError("table_name must be a non-empty string")

    while len(parts) >= 3 and parts[0].lower() == parts[1].lower():
        parts.pop(0)

    if len(parts) == 1:
        return f"{default_db}.{parts[0]}"
    if len(parts) == 2:
        return f"{parts[0]}.{parts[1]}"

    # If a malformed multi-segment path remains, keep only final db.table pair.
    return f"{parts[-2]}.{parts[-1]}"


def unqualify_table_name(table_name: str) -> str:
    """
    Return plain table name with database prefix removed when present.
    Also repairs duplicated db prefixes first (db.db.table -> db.table -> table).
    """
    parts = _split_table_parts(table_name)
    if not parts:
        raise ValueError("table_name must be a non-empty string")

    while len(parts) >= 3 and parts[0].lower() == parts[1].lower():
        parts.pop(0)

    return parts[-1]
