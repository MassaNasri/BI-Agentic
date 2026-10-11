"""
Shared SQL normalization primitives.
"""

from __future__ import annotations
import re


TABLE_REF_PATTERN = re.compile(
    r"\b(FROM|JOIN)\s+((?:`[^`]+`|[A-Za-z_][A-Za-z0-9_]*)(?:\s*\.\s*(?:`[^`]+`|[A-Za-z_][A-Za-z0-9_]*))*)",
    flags=re.IGNORECASE,
)


_CH_SETTINGS_PREFIX_RE = re.compile(
    r"^\s*/\*\s*ch_settings\s*:[\s\S]*?\*/\s*",
    flags=re.IGNORECASE,
)
_TO_DATE_IDENTIFIER_RE = re.compile(
    r"\btoDate\(\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\)",
    flags=re.IGNORECASE,
)


def _upgrade_clickhouse_date_casts(sql: str) -> str:
    """
    Make plain identifier casts resilient for Metabase/ClickHouse runtime.

    ``toDate(col)`` can throw for dirty string/date-time inputs. Converting via
    ``parseDateTimeBestEffortUSOrNull(toString(col))`` and then ``toDate(...)``
    keeps behavior aligned with query-service execution and avoids ``Code: 43``
    argument-type failures from ``toDateOrNull`` on non-string types.
    """

    def _replace(match: re.Match[str]) -> str:
        column_expr = match.group(1).strip()
        return f"toDate(parseDateTimeBestEffortUSOrNull(toString({column_expr})))"

    return _TO_DATE_IDENTIFIER_RE.sub(_replace, sql)


def sanitize_sql_for_metabase(sql: str) -> str:
    """
    Normalize SQL formatting for Metabase native-query compatibility.

    Rules:
    - Trim surrounding whitespace.
    - Remove a leading ``/* ch_settings: ... */`` transport header.
    - Remove one or more trailing semicolons.
    - Preserve SQL content and internal formatting.
    """

    normalized = str(sql or "").strip()
    normalized = _CH_SETTINGS_PREFIX_RE.sub("", normalized, count=1)
    while normalized.endswith(";"):
        normalized = normalized[:-1].rstrip()
    normalized = _upgrade_clickhouse_date_casts(normalized)
    return normalized


def normalize_table_name(table_name: str, default_db: str) -> str:
    """Normalize a table reference into a ClickHouse database-qualified name."""

    if not table_name or not table_name.strip():
        raise ValueError("table_name must be a non-empty string")
    if not default_db or not default_db.strip():
        raise ValueError("default_db must be a non-empty string")

    cleaned = table_name.strip().replace("`", "")
    parts = [part for part in cleaned.split(".") if part]
    if len(parts) == 1:
        normalized_parts = [default_db, parts[0]]
    elif len(parts) == 2:
        normalized_parts = parts
    else:
        normalized_parts = parts[-2:]
    return ".".join(
        part if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) else f"`{part}`"
        for part in normalized_parts
    )


def normalize_sql_table_references(sql: str, default_db: str) -> str:
    """Normalize FROM/JOIN table references in SELECT queries."""

    if not sql or not sql.strip():
        return sql

    def _replace(match: re.Match[str]) -> str:
        clause = match.group(1)
        raw_table = match.group(2)
        normalized = normalize_table_name(raw_table, default_db)
        return f"{clause} {normalized}"

    return TABLE_REF_PATTERN.sub(_replace, sql)
