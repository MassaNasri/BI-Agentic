from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable

try:  # pragma: no cover - dependency is present in service images
    import redis
except Exception:  # noqa: BLE001
    redis = None  # type: ignore[assignment]

from bi_platform_shared.contracts.query import unwrap_clickhouse_type

from preprocessing_high.schemas import HighPreprocessConfig


_SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_VALUE_INDEX_CACHE: dict[str, tuple[float, dict[str, list[dict[str, Any]]]]] = {}
_VALUE_INDEX_CACHE_LOCK = threading.Lock()

_SKIPPED_COLUMN_TOKENS = {
    "id",
    "uuid",
    "guid",
    "hash",
    "token",
    "email",
    "phone",
    "mobile",
    "address",
    "description",
    "notes",
    "note",
    "comment",
    "comments",
    "text",
    "content",
    "password",
    "secret",
}


@dataclass(frozen=True)
class ValueMatchCandidate:
    value: str
    normalized_value: str
    table: str
    column: str
    clickhouse_type: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_value(value: Any) -> str:
    normalized = str(value or "").strip().casefold()
    normalized = normalized.replace("_", " ")
    return re.sub(r"\s+", " ", normalized).strip()


def _log(
    *,
    logger: logging.Logger,
    log_event: Callable[..., None] | None,
    level: int,
    message: str,
    **fields: object,
) -> None:
    if log_event is not None:
        try:
            log_event(logger, level, message, **fields)
            return
        except Exception:  # noqa: BLE001
            pass
    logger.log(level, "%s | %s", message, json.dumps(fields, sort_keys=True, default=str))


def _is_safe_identifier(identifier: str) -> bool:
    return bool(_SAFE_IDENTIFIER_PATTERN.fullmatch(str(identifier or "").strip()))


def _quote_identifier(identifier: str) -> str:
    return f"`{identifier}`"


def _is_skipped_column(name: str) -> bool:
    normalized = str(name or "").strip().lower()
    if not normalized:
        return True
    if normalized == "id" or normalized.endswith("_id"):
        return True
    tokens = set(re.findall(r"[a-z0-9]+", normalized.replace("_", " ")))
    return bool(tokens & _SKIPPED_COLUMN_TOKENS)


def _is_indexable_type(clickhouse_type: str) -> bool:
    inner_type, saw_array = unwrap_clickhouse_type(str(clickhouse_type or ""))
    if saw_array:
        return False
    lowered = inner_type.strip().lower()
    return bool(
        lowered in {"string", "fixedstring"}
        or lowered.startswith("fixedstring(")
        or lowered.startswith("enum8(")
        or lowered.startswith("enum16(")
    )


def _schema_fingerprint(loaded_schema: Any) -> str:
    schema = getattr(loaded_schema, "schema", {}) if loaded_schema is not None else {}
    tables_payload: list[dict[str, Any]] = []
    columns_obj = schema.get("columns", {}) if isinstance(schema, dict) else {}
    if isinstance(columns_obj, dict):
        for table_name, table_columns in sorted(columns_obj.items()):
            columns_payload = []
            if isinstance(table_columns, list):
                for column in table_columns:
                    if not isinstance(column, dict):
                        continue
                    columns_payload.append(
                        {
                            "name": str(column.get("name", "")).strip(),
                            "type": str(column.get("type", "")).strip(),
                        }
                    )
            tables_payload.append({"table": str(table_name).strip(), "columns": columns_payload})
    raw = json.dumps(tables_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _cache_key(loaded_schema: Any, config: HighPreprocessConfig) -> str:
    database = str(getattr(loaded_schema, "database", "") or "").strip()
    user_id = str(getattr(loaded_schema, "user_id", "") or "").strip()
    return (
        "preprocess_high:value_index:"
        f"{database}:{user_id}:{_schema_fingerprint(loaded_schema)}:"
        f"{config.value_index_max_cardinality_threshold}:"
        f"{config.value_index_max_values_per_column}"
    )


def _redis_client(config: HighPreprocessConfig):
    if redis is None or not config.value_index_redis_url:
        return None
    try:
        return redis.Redis.from_url(config.value_index_redis_url, socket_connect_timeout=0.5, socket_timeout=1.0)
    except Exception:  # noqa: BLE001
        return None


def _query_rows(client: Any, sql: str) -> list[Any]:
    result = client.query(sql)
    if hasattr(result, "result_rows"):
        return list(result.result_rows or [])
    if isinstance(result, list):
        return result
    return []


def _first_cell(row: Any) -> Any:
    if isinstance(row, (list, tuple)) and row:
        return row[0]
    if isinstance(row, dict) and row:
        return next(iter(row.values()))
    return None


def _load_cached(
    *,
    key: str,
    config: HighPreprocessConfig,
    redis_client: Any,
    logger: logging.Logger,
    log_event: Callable[..., None] | None,
) -> dict[str, list[dict[str, Any]]] | None:
    now = time.time()
    if config.value_index_cache_ttl_seconds > 0:
        with _VALUE_INDEX_CACHE_LOCK:
            cached = _VALUE_INDEX_CACHE.get(key)
            if cached and (now - cached[0]) < config.value_index_cache_ttl_seconds:
                return cached[1]

    if redis_client is None:
        return None
    try:
        raw = redis_client.get(key)
    except Exception as exc:  # noqa: BLE001
        _log(
            logger=logger,
            log_event=log_event,
            level=logging.WARNING,
            message="Value index Redis read failed",
            error=str(exc),
        )
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else str(raw))
    except Exception as exc:  # noqa: BLE001
        _log(
            logger=logger,
            log_event=log_event,
            level=logging.WARNING,
            message="Value index cache payload could not be decoded",
            error=str(exc),
        )
        return None
    if not isinstance(payload, dict):
        return None
    normalized: dict[str, list[dict[str, Any]]] = {}
    for key_value, candidates in payload.items():
        if isinstance(candidates, list):
            normalized[str(key_value)] = [item for item in candidates if isinstance(item, dict)]
    if config.value_index_cache_ttl_seconds > 0:
        with _VALUE_INDEX_CACHE_LOCK:
            _VALUE_INDEX_CACHE[key] = (now, normalized)
    return normalized


def _store_cached(
    *,
    key: str,
    payload: dict[str, list[dict[str, Any]]],
    config: HighPreprocessConfig,
    redis_client: Any,
    logger: logging.Logger,
    log_event: Callable[..., None] | None,
) -> None:
    now = time.time()
    if config.value_index_cache_ttl_seconds > 0:
        with _VALUE_INDEX_CACHE_LOCK:
            _VALUE_INDEX_CACHE[key] = (now, payload)
    if redis_client is None or config.value_index_cache_ttl_seconds <= 0:
        return
    try:
        redis_client.setex(
            key,
            config.value_index_cache_ttl_seconds,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
    except Exception as exc:  # noqa: BLE001
        _log(
            logger=logger,
            log_event=log_event,
            level=logging.WARNING,
            message="Value index Redis write failed",
            error=str(exc),
        )


def _iter_indexable_columns(loaded_schema: Any) -> list[tuple[str, str, str]]:
    schema = getattr(loaded_schema, "schema", {}) if loaded_schema is not None else {}
    columns_obj = schema.get("columns", {}) if isinstance(schema, dict) else {}
    output: list[tuple[str, str, str]] = []
    if not isinstance(columns_obj, dict):
        return output
    for table_name, table_columns in columns_obj.items():
        table = str(table_name or "").strip()
        if not _is_safe_identifier(table) or not isinstance(table_columns, list):
            continue
        for column in table_columns:
            if not isinstance(column, dict):
                continue
            column_name = str(column.get("name", "")).strip()
            clickhouse_type = str(column.get("type", "")).strip()
            if (
                not _is_safe_identifier(column_name)
                or _is_skipped_column(column_name)
                or not _is_indexable_type(clickhouse_type)
            ):
                continue
            output.append((table, column_name, clickhouse_type))
    return output


def load_value_index(
    *,
    loaded_schema: Any,
    config: HighPreprocessConfig,
    logger: logging.Logger,
    log_event: Callable[..., None] | None = None,
    clickhouse_client: Any | None = None,
    redis_client: Any | None = None,
) -> dict[str, list[dict[str, Any]]]:
    if not config.value_index_enabled:
        return {}

    database = str(getattr(loaded_schema, "database", "") or "").strip()
    if not _is_safe_identifier(database):
        return {}

    key = _cache_key(loaded_schema, config)
    cache_client = redis_client if redis_client is not None else _redis_client(config)
    cached = _load_cached(
        key=key,
        config=config,
        redis_client=cache_client,
        logger=logger,
        log_event=log_event,
    )
    if cached is not None:
        return cached

    indexable_columns = _iter_indexable_columns(loaded_schema)
    if not indexable_columns:
        return {}

    # Foundation-A removes AI's authority to construct a product-data
    # ClickHouse client. A future BIA-021 authorized Query/Schema tool may
    # inject a bounded provider here; until then this feature fails closed.
    if clickhouse_client is None:
        _log(
            logger=logger,
            log_event=log_event,
            level=logging.WARNING,
            message="Value index provider unavailable",
            database=database,
        )
        return {}
    client = clickhouse_client

    value_index: dict[str, list[dict[str, Any]]] = {}
    max_cardinality = int(config.value_index_max_cardinality_threshold)
    max_values = int(config.value_index_max_values_per_column)

    for table, column, clickhouse_type in indexable_columns:
        qualified_column = _quote_identifier(column)
        qualified_table = f"{_quote_identifier(database)}.{_quote_identifier(table)}"
        cardinality_sql = (
            "SELECT count() FROM ("
            f"SELECT DISTINCT {qualified_column} FROM {qualified_table} "
            f"WHERE {qualified_column} IS NOT NULL LIMIT {max_cardinality + 1}"
            ")"
        )
        try:
            cardinality_rows = _query_rows(client, cardinality_sql)
            cardinality = int(_first_cell(cardinality_rows[0]) or 0) if cardinality_rows else 0
        except Exception as exc:  # noqa: BLE001
            _log(
                logger=logger,
                log_event=log_event,
                level=logging.WARNING,
                message="Value index cardinality query failed",
                table=table,
                column=column,
                error=str(exc),
            )
            continue

        if cardinality <= 0 or cardinality > max_cardinality:
            continue

        values_sql = (
            f"SELECT DISTINCT {qualified_column} FROM {qualified_table} "
            f"WHERE {qualified_column} IS NOT NULL LIMIT {max_values + 1}"
        )
        try:
            value_rows = _query_rows(client, values_sql)
        except Exception as exc:  # noqa: BLE001
            _log(
                logger=logger,
                log_event=log_event,
                level=logging.WARNING,
                message="Value index values query failed",
                table=table,
                column=column,
                error=str(exc),
            )
            continue

        if len(value_rows) > max_values:
            continue

        for row in value_rows:
            raw_value = _first_cell(row)
            if raw_value is None or isinstance(raw_value, (dict, list, tuple)):
                continue
            value = str(raw_value).strip()
            normalized = normalize_value(value)
            if not value or not normalized:
                continue
            candidate = ValueMatchCandidate(
                value=value,
                normalized_value=normalized,
                table=table,
                column=column,
                clickhouse_type=clickhouse_type,
            ).to_dict()
            candidates = value_index.setdefault(normalized, [])
            if candidate not in candidates:
                candidates.append(candidate)

    _store_cached(
        key=key,
        payload=value_index,
        config=config,
        redis_client=cache_client,
        logger=logger,
        log_event=log_event,
    )
    _log(
        logger=logger,
        log_event=log_event,
        level=logging.INFO,
        message="Loaded value index for high preprocessing",
        database=database,
        indexed_values=len(value_index),
        indexed_columns=len(indexable_columns),
    )
    return value_index


__all__ = ["ValueMatchCandidate", "load_value_index", "normalize_value"]
