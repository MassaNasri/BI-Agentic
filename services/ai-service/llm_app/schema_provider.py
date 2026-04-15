import logging
import os
import re
import time
from typing import Any

import clickhouse_connect

from shared.schema_utils import is_date_type, is_dimension_type, is_numeric_type, unqualify_table_name
from shared.schema_filtering import filter_business_schema

logger = logging.getLogger(__name__)

_SCHEMA_CACHE: dict[str, list[dict[str, Any]]] | None = None
_SCHEMA_CACHE_AT = 0.0
SCHEMA_CACHE_TTL_SECONDS = int(os.getenv("SCHEMA_CACHE_TTL_SECONDS", "60"))


def sanitize_sql_for_http(sql: str) -> str:
    if not sql:
        return ""
    clean_sql = re.sub(r"\s+FORMAT\s+Native\s*", " ", sql, flags=re.IGNORECASE)
    clean_sql = clean_sql.replace(";", "")
    clean_sql = " ".join(clean_sql.split())
    return clean_sql.strip()


def get_query_clickhouse_client():
    host = os.getenv("CLICKHOUSE_HOST", "localhost")
    port = int(os.getenv("CLICKHOUSE_PORT", "8123"))
    username = os.getenv("CLICKHOUSE_USER", "etl_user")
    password = os.getenv("CLICKHOUSE_PASSWORD", "etl_pass123")
    database = os.getenv("CLICKHOUSE_DATABASE", "etl")

    logger.info("Connecting to ClickHouse for schema read: %s:%s db=%s", host, port, database)

    try:
        return clickhouse_connect.get_client(
            host=host,
            port=port,
            username=username,
            password=password,
            database=database,
        )
    except Exception as exc:
        raise RuntimeError(
            f"ClickHouse connection error (schema read): host={host}, port={port}, db={database}. {exc}"
        ) from exc


def _classify_column(column: str, col_type: str) -> dict[str, Any]:
    return {
        "name": column,
        "type": col_type,
        "is_numeric": is_numeric_type(col_type),
        "is_date": is_date_type(col_type),
        "is_dimension": is_dimension_type(col_type),
    }


def _fetch_schema_from_clickhouse() -> dict[str, list[dict[str, Any]]]:
    client = get_query_clickhouse_client()

    schema_query = """
        SELECT table, name, type
        FROM system.columns
        WHERE database = currentDatabase()
        ORDER BY table, position;
    """
    clean_query = sanitize_sql_for_http(schema_query)

    try:
        result = client.query(clean_query)
    except Exception as exc:
        raise RuntimeError(f"ClickHouse schema query failed: {exc}") from exc

    schema: dict[str, list[dict[str, Any]]] = {}
    for table, column, col_type in result.result_rows:
        normalized_table = unqualify_table_name(str(table))
        schema.setdefault(normalized_table, []).append(_classify_column(column, col_type))

    if not schema:
        raise RuntimeError("No tables found in current ClickHouse database")
    filtered_schema, _ = filter_business_schema(schema)
    return filtered_schema or schema


def get_schema(*, force_refresh: bool = False) -> dict[str, list[dict[str, Any]]]:
    global _SCHEMA_CACHE, _SCHEMA_CACHE_AT

    now = time.time()
    cache_valid = (
        not force_refresh
        and _SCHEMA_CACHE is not None
        and (now - _SCHEMA_CACHE_AT) < SCHEMA_CACHE_TTL_SECONDS
    )
    if cache_valid:
        return _SCHEMA_CACHE

    schema = _fetch_schema_from_clickhouse()
    _SCHEMA_CACHE = schema
    _SCHEMA_CACHE_AT = now
    return schema


def is_question_matching_schema(question: str, schema: dict[str, list[dict[str, Any]]]) -> bool:
    question_lower = question.lower()
    tokens = set()

    for table, columns in schema.items():
        tokens.add(table.split(".")[-1].lower())
        for col in columns:
            col_name = col["name"].lower()
            tokens.add(col_name)
            tokens.add(col_name.replace("_", " "))

    return any(token in question_lower for token in tokens)
