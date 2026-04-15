from __future__ import annotations

import importlib
from functools import lru_cache
from typing import Any, Callable

from intent_extraction.error_handler import (
    IntentExtractionSchemaMismatchError,
    IntentExtractionSystemError,
)
from intent_extraction.schemas import IntentExtractionConfig, NextStepType, StructuredIntent
from shared.query_planner import normalize_analytical_intent
from shared.sql_compiler import compile_sql
from shared.sql_validator import validate_sql


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
        intent=intent,
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
