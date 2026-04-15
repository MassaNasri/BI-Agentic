from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable

import clickhouse_connect

from preprocessing_high.error_handler import (
    PreprocessHighInputError,
    PreprocessHighSchemaLoadError,
)
from preprocessing_high.schemas import HighPreprocessConfig, UserSchema
from shared.schema_filtering import filter_business_schema
from shared.schema_utils import is_date_type, unqualify_table_name


_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SCHEMA_CACHE: dict[str, tuple[float, "LoadedUserSchema"]] = {}
_SCHEMA_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class ColumnReference:
    table: str
    name: str
    type: str


@dataclass(frozen=True)
class LoadedUserSchema:
    user_id: str
    database: str
    schema: UserSchema
    columns_by_name: dict[str, list[ColumnReference]]
    date_columns_by_name: dict[str, list[ColumnReference]]

    def total_columns(self) -> int:
        return sum(len(cols) for cols in self.schema["columns"].values())


def _sanitize_user_id(user_id: str) -> str:
    if user_id is None:
        raise PreprocessHighInputError("user_id is required.")

    normalized = str(user_id).strip()
    if not normalized:
        raise PreprocessHighInputError("user_id is empty.")

    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", normalized)
    if not sanitized:
        raise PreprocessHighInputError("user_id is invalid after sanitization.")
    return sanitized


def _ensure_safe_identifier(identifier: str, *, field_name: str) -> str:
    if not identifier or not _SAFE_IDENTIFIER_PATTERN.fullmatch(identifier):
        raise PreprocessHighSchemaLoadError(
            f"{field_name} contains unsafe characters and cannot be used in ClickHouse query."
        )
    return identifier


def _resolve_database_name(user_id: str, config: HighPreprocessConfig) -> str:
    if config.user_database_template:
        try:
            database_name = config.user_database_template.format(user_id=user_id)
        except Exception as exc:  # noqa: BLE001
            raise PreprocessHighSchemaLoadError(
                "PREPROCESS_HIGH_DATABASE_TEMPLATE is invalid."
            ) from exc
    else:
        database_name = config.clickhouse_default_database

    return _ensure_safe_identifier(database_name, field_name="database")


def _cache_key(user_id: str, database: str) -> str:
    return f"{database}:{user_id}"


def _build_clickhouse_client(config: HighPreprocessConfig, *, database: str):
    try:
        return clickhouse_connect.get_client(
            host=config.clickhouse_host,
            port=config.clickhouse_port,
            username=config.clickhouse_user,
            password=config.clickhouse_password,
            database=database,
        )
    except Exception as exc:  # noqa: BLE001
        raise PreprocessHighSchemaLoadError(
            "Failed to connect to ClickHouse for schema loading."
        ) from exc


def _fetch_user_schema_rows(
    *,
    config: HighPreprocessConfig,
    database: str,
) -> list[tuple[str, str, str]]:
    client = _build_clickhouse_client(config, database=database)
    query = (
        "SELECT table, name, type "
        "FROM system.columns "
        f"WHERE database = '{database}' "
        "ORDER BY table, position"
    )

    try:
        result = client.query(query)
    except Exception as exc:  # noqa: BLE001
        raise PreprocessHighSchemaLoadError("Failed to query schema from ClickHouse.") from exc

    rows = result.result_rows if hasattr(result, "result_rows") else []
    if not rows:
        raise PreprocessHighSchemaLoadError(
            f"No tables were found for database '{database}'."
        )
    return rows


def _build_loaded_schema(
    *,
    user_id: str,
    database: str,
    rows: list[tuple[str, str, str]],
) -> LoadedUserSchema:
    raw_columns: dict[str, list[dict[str, str]]] = {}
    for table_raw, column_raw, col_type_raw in rows:
        table_name = unqualify_table_name(str(table_raw))
        column_name = str(column_raw)
        column_type = str(col_type_raw)
        raw_columns.setdefault(table_name, []).append({"name": column_name, "type": column_type})

    filtered_columns, _ = filter_business_schema(raw_columns)
    columns = filtered_columns if filtered_columns else raw_columns
    tables = sorted(columns.keys())

    columns_by_name: dict[str, list[ColumnReference]] = {}
    date_columns_by_name: dict[str, list[ColumnReference]] = {}
    for table_name, table_columns in columns.items():
        for column in table_columns:
            column_name = str(column.get("name", "")).strip()
            column_type = str(column.get("type", "")).strip()
            if not column_name:
                continue

            reference = ColumnReference(table=table_name, name=column_name, type=column_type)
            columns_by_name.setdefault(column_name.lower(), []).append(reference)
            if is_date_type(column_type):
                date_columns_by_name.setdefault(column_name.lower(), []).append(reference)

    schema: UserSchema = {"tables": tables, "columns": columns}
    return LoadedUserSchema(
        user_id=user_id,
        database=database,
        schema=schema,
        columns_by_name=columns_by_name,
        date_columns_by_name=date_columns_by_name,
    )


def load_user_schema(
    *,
    user_id: str,
    config: HighPreprocessConfig,
    logger: logging.Logger,
    log_event: Callable[..., None],
) -> LoadedUserSchema:
    sanitized_user_id = _sanitize_user_id(user_id)
    database = _resolve_database_name(sanitized_user_id, config)
    key = _cache_key(sanitized_user_id, database)
    now = time.time()

    if config.schema_cache_ttl_seconds > 0:
        with _SCHEMA_CACHE_LOCK:
            cached = _SCHEMA_CACHE.get(key)
            if cached and (now - cached[0]) < config.schema_cache_ttl_seconds:
                log_event(
                    logger,
                    logging.INFO,
                    "Using cached schema for high preprocessing",
                    user_id=sanitized_user_id,
                    database=database,
                    table_count=len(cached[1].schema["tables"]),
                    column_count=cached[1].total_columns(),
                )
                return cached[1]

    rows = _fetch_user_schema_rows(config=config, database=database)
    loaded = _build_loaded_schema(user_id=sanitized_user_id, database=database, rows=rows)

    if config.schema_cache_ttl_seconds > 0:
        with _SCHEMA_CACHE_LOCK:
            _SCHEMA_CACHE[key] = (now, loaded)

    log_event(
        logger,
        logging.INFO,
        "Loaded user schema for high preprocessing",
        user_id=sanitized_user_id,
        database=database,
        table_count=len(loaded.schema["tables"]),
        column_count=loaded.total_columns(),
    )
    return loaded


def find_column_matches(
    *,
    loaded_schema: LoadedUserSchema,
    column_name: str,
    table_name: str | None = None,
) -> list[ColumnReference]:
    normalized_column = str(column_name or "").strip().lower()
    if not normalized_column:
        return []

    matches = loaded_schema.columns_by_name.get(normalized_column, [])
    if not table_name:
        return matches

    normalized_table = str(table_name).strip().split(".")[-1].lower()
    if not normalized_table:
        return matches

    return [match for match in matches if match.table.lower() == normalized_table]


def get_fallback_derivable_column(loaded_schema: LoadedUserSchema) -> ColumnReference | None:
    for references in loaded_schema.date_columns_by_name.values():
        if references:
            return references[0]
    return None
