from __future__ import annotations

import importlib
import re
from functools import lru_cache
from typing import Any, Callable

from intent_extraction.error_handler import (
    IntentExtractionSchemaMismatchError,
    IntentExtractionSystemError,
)
from intent_extraction.schemas import IntentExtractionConfig, NextStepType, StructuredIntent
from shared.pipeline_guards import is_technical_column_name
from shared.query_planner import normalize_analytical_intent
from shared.sql_compiler import compile_sql
from shared.sql_validator import validate_sql

_GRANULARITY_TO_CLICKHOUSE_EXPR = {
    "hour": "toStartOfHour({column})",
    "day": "toDate({column})",
    "week": "toStartOfWeek({column})",
    "month": "toStartOfMonth({column})",
    "year": "toStartOfYear({column})",
}


def _is_string_like_type(column_type: str) -> bool:
    lowered = str(column_type or "").strip().lower()
    return any(token in lowered for token in ("string", "fixedstring", "varchar", "char"))


def _normalize_clickhouse_date_casts(sql_expr: str) -> str:
    normalized = str(sql_expr or "").strip()
    if not normalized:
        return normalized
    previous = ""
    while normalized != previous:
        previous = normalized
        normalized = re.sub(
            r"toDate\(\s*toDate\(\s*([^)]+?)\s*\)\s*\)",
            r"toDate(\1)",
            normalized,
            flags=re.IGNORECASE,
        )
    return normalized


def _build_predictive_time_expr(
    *,
    granularity: str,
    column_name: str,
    column_type: str,
) -> str:
    template = _GRANULARITY_TO_CLICKHOUSE_EXPR.get(granularity, "toDate({column})")
    if granularity == "day" and ("date" in column_type and "datetime" not in column_type and "timestamp" not in column_type):
        return column_name
    base_column = f"toDate({column_name})" if _is_string_like_type(column_type) else column_name
    expr = template.format(column=base_column)
    return _normalize_clickhouse_date_casts(expr)


def _build_query_builder_payload(intent: StructuredIntent) -> dict[str, Any]:
    order_by = intent.get("order_by", []) or []
    limit = intent.get("limit")
    metric_specs_payload: list[dict[str, Any]] = []

    for metric_spec in intent.get("metric_specs", []) or []:
        if not isinstance(metric_spec, dict):
            continue
        column = str(metric_spec.get("column", "")).strip()
        if not column:
            continue
        metric_agg = str(metric_spec.get("aggregation", "")).strip().upper() or None
        metric_alias = str(metric_spec.get("alias", "")).strip() or None
        metric_specs_payload.append(
            {
                "column": column,
                "aggregation": metric_agg,
                "alias": metric_alias,
            }
        )

    metrics_payload = [
        str(metric_column).strip()
        for metric_column in (intent.get("metrics", []) or [])
        if str(metric_column).strip()
    ]

    if not metrics_payload and not metric_specs_payload:
        target_column = str(intent.get("target_column", "*") or "*").strip() or "*"
        metrics_payload = [target_column]

    return {
        "table": intent["table"],
        "intent": str(intent.get("intent", "analytical") or "analytical"),
        "operations": intent.get("operations", []),
        "metric_specs": metric_specs_payload,
        "metrics": metrics_payload,
        "dimensions": intent.get("dimensions", []),
        "filters": intent.get("filters", []),
        "order_by": order_by,
        "limit": limit,
        "ranking": intent.get("ranking", {}),
        "ambiguities": intent.get("ambiguities", []),
    }


def _is_schema_mismatch_message(message: str) -> bool:
    lowered = message.lower()
    return (
        "table" in lowered
        or "column" in lowered
        or "schema" in lowered
        or "does not exist" in lowered
        or "ambiguous table name" in lowered
        or "no numeric columns" in lowered
    )


def build_sql_from_intent(
    *,
    query: str,
    intent: StructuredIntent,
    schema: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any], str]:
    if str(intent.get("intent_type", "")).strip().lower() == "predictive":
        return _build_historical_forecast_sql(intent=intent, schema=schema)

    query_builder_payload = _build_query_builder_payload(intent)

    try:
        normalized_intent = normalize_analytical_intent(
            question=query,
            raw_intent=query_builder_payload,
            schema=schema,
        )
        sql_query = compile_sql(normalized_intent, schema=schema)
        validate_sql(sql_query)
    except ValueError as exc:
        if _is_schema_mismatch_message(str(exc)):
            raise IntentExtractionSchemaMismatchError(str(exc)) from exc
        raise

    return normalized_intent, sql_query


def _resolve_schema_table(schema: dict[str, list[dict[str, Any]]], requested_table: str) -> str:
    requested = str(requested_table or "").strip()
    if requested in schema:
        return requested
    if requested:
        requested_unqualified = requested.split(".")[-1].lower()
        matches = [
            table_name
            for table_name in schema.keys()
            if table_name.split(".")[-1].lower() == requested_unqualified
        ]
        if len(matches) == 1:
            return matches[0]
    if not schema:
        raise IntentExtractionSchemaMismatchError("Schema is empty.")
    return sorted(schema.keys())[0]


def _resolve_schema_column(
    *,
    table_columns: list[dict[str, Any]],
    requested_column: str,
) -> str:
    requested = str(requested_column or "").strip()
    if not requested:
        return ""
    exact = [
        str(column.get("name", "")).strip()
        for column in table_columns
        if str(column.get("name", "")).strip().lower() == requested.lower()
    ]
    if exact:
        return exact[0]
    normalized_requested = requested.lower().replace(" ", "_")
    normalized = [
        str(column.get("name", "")).strip()
        for column in table_columns
        if str(column.get("name", "")).strip().lower() == normalized_requested
    ]
    if normalized:
        return normalized[0]
    return ""


def _build_historical_forecast_sql(
    *,
    intent: StructuredIntent,
    schema: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any], str]:
    resolved_table = _resolve_schema_table(schema, str(intent.get("table", "")).strip())
    table_columns = schema.get(resolved_table, [])
    if not table_columns:
        raise IntentExtractionSchemaMismatchError(f"Table '{resolved_table}' not found in schema.")

    metric = (
        str(intent.get("metric", "")).strip()
        or str(intent.get("target_column", "")).strip()
        or (str((intent.get("metrics") or [""])[0]).strip() if isinstance(intent.get("metrics"), list) else "")
    )
    time_column = (
        str(intent.get("time_column", "")).strip()
        or (str((intent.get("dimensions") or [""])[0]).strip() if isinstance(intent.get("dimensions"), list) else "")
    )

    resolved_metric = _resolve_schema_column(table_columns=table_columns, requested_column=metric)
    resolved_time_column = _resolve_schema_column(table_columns=table_columns, requested_column=time_column)
    if not resolved_metric:
        raise IntentExtractionSchemaMismatchError(
            f"Predictive metric column '{metric}' was not found in table '{resolved_table}'."
        )
    if not resolved_time_column:
        raise IntentExtractionSchemaMismatchError(
            f"Predictive time column '{time_column}' was not found in table '{resolved_table}'."
        )
    if is_technical_column_name(resolved_time_column):
        raise IntentExtractionSchemaMismatchError(
            f"Predictive time column '{resolved_time_column}' is technical metadata and cannot be used."
        )

    granularity = str(intent.get("granularity", "day") or "day").strip().lower() or "day"
    resolved_time_type = ""
    for column in table_columns:
        if str(column.get("name", "")).strip().lower() == resolved_time_column.lower():
            resolved_time_type = str(column.get("type", "")).strip().lower()
            break
    if granularity == "day" and resolved_time_column.lower() in {"ds", "date"} and not _is_string_like_type(resolved_time_type):
        time_expr = resolved_time_column
    else:
        time_expr = _build_predictive_time_expr(
            granularity=granularity,
            column_name=resolved_time_column,
            column_type=resolved_time_type,
        )
    value_expr = f"sum(toFloat64({resolved_metric}))"

    sql_query = (
        f"SELECT {time_expr} AS ds, {value_expr} AS value "
        f"FROM {resolved_table} "
        f"WHERE {resolved_time_column} IS NOT NULL AND {resolved_metric} IS NOT NULL "
        "GROUP BY ds "
        "ORDER BY ds ASC"
    )
    validate_sql(sql_query)

    normalized_intent = {
        "intent_type": "predictive",
        "table": resolved_table,
        "intent": "forecast",
        "operations": ["projection", "forecasting"],
        "metrics": [{"column": resolved_metric, "aggregation": "SUM", "alias": "value"}],
        "dimensions": [resolved_time_column],
        "filters": [],
        "aggregation": "SUM",
        "ranking": {"direction": "ASC", "requested": True, "source": "predictive_sql_builder"},
        "order_by": [{"column": "ds", "direction": "ASC"}],
        "limit": None,
        "ambiguities": [],
        "metric": resolved_metric,
        "time_column": resolved_time_column,
        "forecast_horizon": intent.get("forecast_horizon", intent.get("horizon", 7)),
        "granularity": granularity,
        "requires_forecast": True,
        "question_type": "predictive",
        "time_column_expression": time_expr,
    }
    return normalized_intent, sql_query


@lru_cache(maxsize=16)
def _load_callable_from_path(path: str) -> Callable[..., Any] | None:
    if not path:
        return None
    if ":" not in path:
        raise IntentExtractionSystemError(
            f"Invalid integration path '{path}'. Expected format module.submodule:function_name."
        )

    module_path, function_name = path.split(":", 1)
    try:
        module = importlib.import_module(module_path)
    except Exception as exc:  # noqa: BLE001
        raise IntentExtractionSystemError(
            f"Failed to import integration module '{module_path}': {exc}"
        ) from exc

    handler = getattr(module, function_name, None)
    if handler is None or not callable(handler):
        raise IntentExtractionSystemError(
            f"Integration handler '{function_name}' not found or not callable in '{module_path}'."
        )
    return handler


def _call_handler(handler: Callable[..., Any], payload: dict[str, Any]) -> Any:
    try:
        return handler(payload)
    except TypeError:
        if "sql_query" in payload:
            return handler(payload["sql_query"])
        raise


def _execute_clickhouse(
    *,
    sql_query: str,
    normalized_intent: dict[str, Any],
    config: IntentExtractionConfig,
) -> Any:
    handler = _load_callable_from_path(config.clickhouse_executor_path)
    if handler is None:
        return {
            "status": "pending_integration",
            "message": "ClickHouse execution handler is not configured.",
            "sql_query": sql_query,
        }

    payload = {
        "sql_query": sql_query,
        "intent": normalized_intent,
    }
    try:
        return _call_handler(handler, payload)
    except Exception as exc:  # noqa: BLE001
        raise IntentExtractionSystemError(f"ClickHouse execution handler failed: {exc}") from exc


def execute_clickhouse_query(
    *,
    sql_query: str,
    normalized_intent: dict[str, Any],
    config: IntentExtractionConfig,
) -> Any:
    """
    Public wrapper for ClickHouse execution stage.
    """
    return _execute_clickhouse(
        sql_query=sql_query,
        normalized_intent=normalized_intent,
        config=config,
    )


def _route_downstream(
    *,
    intent: StructuredIntent,
    sql_query: str,
    execution_result: Any,
    config: IntentExtractionConfig,
) -> tuple[NextStepType, Any]:
    if intent["intent_type"] == "predictive":
        next_step: NextStepType = "forecasting"
        handler_path = config.forecasting_handler_path
        payload = {
            "historical_data": execution_result,
            "sql_query": sql_query,
            "intent": intent,
        }
    else:
        next_step = "metabase"
        handler_path = config.metabase_handler_path
        payload = {
            "execution_result": execution_result,
            "sql_query": sql_query,
            "intent": intent,
        }

    handler = _load_callable_from_path(handler_path)
    if handler is None:
        return next_step, {
            "status": "pending_integration",
            "message": f"{next_step} handler is not configured.",
            "next_step": next_step,
        }

    try:
        return next_step, _call_handler(handler, payload)
    except Exception as exc:  # noqa: BLE001
        raise IntentExtractionSystemError(f"{next_step} handler failed: {exc}") from exc


def execute_downstream_route(
    *,
    intent: StructuredIntent,
    sql_query: str,
    execution_result: Any,
    config: IntentExtractionConfig,
) -> tuple[NextStepType, Any]:
    """
    Public wrapper for route-specific downstream execution
    (analytical -> Metabase, predictive -> forecasting).
    """
    return _route_downstream(
        intent=intent,
        sql_query=sql_query,
        execution_result=execution_result,
        config=config,
    )


def route_intent(
    *,
    query: str,
    intent: StructuredIntent,
    schema: dict[str, list[dict[str, Any]]],
    config: IntentExtractionConfig,
) -> dict[str, Any]:
    normalized_intent, sql_query = build_sql_from_intent(
        query=query,
        intent=intent,
        schema=schema,
    )
    execution_result = execute_clickhouse_query(
        sql_query=sql_query,
        normalized_intent=normalized_intent,
        config=config,
    )
    next_step, downstream_result = execute_downstream_route(
        intent=normalized_intent,  # ensure predictive invariants propagate downstream
        sql_query=sql_query,
        execution_result=execution_result,
        config=config,
    )
    return {
        "sql_query": sql_query,
        "next_step": next_step,
        "normalized_intent": normalized_intent,
        "execution_result": execution_result,
        "downstream_result": downstream_result,
    }
