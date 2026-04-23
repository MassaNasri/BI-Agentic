from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable

import requests

from intent_extraction.error_handler import (
    IntentExtractionModelOutputError,
    IntentExtractionSystemError,
)
from intent_extraction.schemas import IntentExtractionConfig, IntentType, StructuredIntent
from llm_app.response_parser import safe_json_parse
from shared.query_planner import normalize_analytical_intent


_PREDICTIVE_KEYWORDS = (
    # English
    "forecast",
    "predict",
    "prediction",
    "projected",
    "projection",
    "expected",
    "expectation",
    "future",
    "next",
    "upcoming",
    "what will",
    # Arabic
    "توقع",
    "تنبؤ",
    "متوقع",
    "المستقبل",
    "القادم",
    "المقبل",
    # French
    "prevision",
    "prévision",
    "predire",
    "prédire",
    "avenir",
    "prochain",
    # Spanish
    "pronostico",
    "pronóstico",
    "prediccion",
    "predicción",
    "predecir",
    "futuro",
    "proximo",
    "próximo",
    # German
    "prognose",
    "vorhersage",
    "zukunft",
    "naechste",
    "nächste",
    # Turkish
    "tahmin",
    "ongoru",
    "öngörü",
    "gelecek",
    # Hindi
    "पूर्वानुमान",
)

_FUTURE_TIME_PATTERNS = (
    r"\bnext\s+(week|month|quarter|year)\b",
    r"\bupcoming\s+(week|month|quarter|year)\b",
    r"\bcoming\s+(week|month|quarter|year)\b",
    r"\bin\s+\d+\s+(day|days|week|weeks|month|months|quarter|quarters|year|years)\b",
    r"\bwhat\s+will\s+be\b",
    r"\btrend\b.*\bnext\b",
)

_VALID_INTENT_TYPES = {"analytical", "predictive"}
_RELATIONSHIP_KEYWORDS = (
    "relationship",
    "correlation",
    "associated",
    "association",
    "related",
    "relation",
    "vs",
    "versus",
)


def _schema_to_prompt(schema: dict[str, list[dict[str, Any]]]) -> str:
    lines: list[str] = []
    for table, columns in schema.items():
        lines.append(f"Table: {table}")
        for col in columns:
            col_name = str(col.get("name", "")).strip()
            col_type = str(col.get("type", "")).strip()
            lines.append(f"  - {col_name} ({col_type})")
    return "\n".join(lines)


def _build_extraction_prompt(*, query: str, schema: dict[str, list[dict[str, Any]]]) -> str:
    return f"""
You are a domain-agnostic semantic intent extraction engine for BI and analytics.

Your job:
1) Infer intent_type: "analytical" or "predictive".
2) Extract a COMPLETE IR payload for SQL planning.
3) Output STRICT JSON only (no markdown, no prose, no code fences).

Hard constraints:
- Use only columns/tables from the provided schema.
- Do not generate SQL.
- Do not drop requested metrics, dimensions, filters, ranking, or limits.
- If query implies ranking keywords (highest, lowest, top, bottom, best, worst), include order_by and ranking.direction.
- If query implies top/bottom/first/last N, include limit=N.
- If query implies comparisons (above, below, greater than, less than, more than, fewer than, >=, <=, =), map them into filters with explicit operators.
- If query asks multiple outputs ("A and B", "X with Y"), include all relevant metrics in both metrics and metric_specs.
- If aggregation intent appears (sum/total, avg/mean, count), set metric_specs.aggregation and aggregation accordingly.
- If unsure, choose safest valid values but keep structure complete.

Schema:
{_schema_to_prompt(schema)}

Return exactly one JSON object with these keys:
{{
  "intent_type": "analytical|predictive",
  "table": "table_name",
  "intent": "projection|filtering|aggregation|ranking",
  "metrics": ["metric_column_name", "..."],
  "metric_specs": [
    {{"column": "metric_column_name", "aggregation": "SUM|AVG|COUNT|MIN|MAX|null", "alias": "optional_alias"}}
  ],
  "dimensions": ["dimension_column_name", "..."],
  "filters": [
    {{"column": "column_name", "operator": "=|!=|>|<|>=|<=|IN|LIKE|BETWEEN", "value": "scalar_or_array"}}
  ],
  "aggregation": "SUM|AVG|COUNT|MIN|MAX|MIXED|null",
  "target_column": "primary_metric_column_or_*",
  "time_range": "time window string or all_time",
  "order_by": [{{"column": "column_or_metric_alias", "direction": "ASC|DESC"}}],
  "limit": 1,
  "ranking": {{"direction": "ASC|DESC|null", "requested": true, "source": "query|model"}},
  "operations": ["projection", "aggregation", "grouping", "filtering", "ranking", "limiting", "comparison"],
  "ambiguities": [{{"type": "string", "message": "string"}}]
}}

User query:
{query}
""".strip()


def _extract_json(raw_output: str) -> dict[str, Any]:
    try:
        parsed = safe_json_parse(raw_output)
    except Exception as exc:  # noqa: BLE001
        raise IntentExtractionModelOutputError(f"Invalid JSON returned by model: {exc}") from exc
    if not isinstance(parsed, dict):
        raise IntentExtractionModelOutputError("Model output must be a JSON object.")
    return parsed


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise IntentExtractionModelOutputError("Expected list for metrics/dimensions.")

    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
            continue
        if isinstance(item, dict):
            candidate = (
                item.get("column")
                or item.get("name")
                or item.get("field")
            )
            if isinstance(candidate, str) and candidate.strip():
                result.append(candidate.strip())
                continue
        raise IntentExtractionModelOutputError("Metrics/dimensions entries must be strings or objects with column.")
    return result


def _normalize_filters(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        raise IntentExtractionModelOutputError("Expected list for filters.")

    normalized: list[dict[str, Any]] = []
    operator_aliases = {
        "ABOVE": ">",
        "BELOW": "<",
        "GREATER THAN": ">",
        "LESS THAN": "<",
        "MORE THAN": ">",
        "FEWER THAN": "<",
        "=>": ">=",
        "=<": "<=",
        "==": "=",
    }
    for item in value:
        if not isinstance(item, dict):
            raise IntentExtractionModelOutputError("Each filter must be an object.")
        column = str(item.get("column", "")).strip()
        if not column:
            continue
        operator = str(item.get("operator", "=")).strip().upper() or "="
        operator = operator_aliases.get(operator, operator)
        normalized.append(
            {
                "column": column,
                "operator": operator,
                "value": item.get("value"),
            }
        )
    return normalized


def _normalize_metric_specs(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        raise IntentExtractionModelOutputError("Expected list for metric_specs.")

    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        column = str(item.get("column", "")).strip()
        if not column:
            continue
        aggregation = str(item.get("aggregation", "")).strip().upper() or None
        alias = str(item.get("alias", "")).strip() or None
        normalized.append(
            {
                "column": column,
                "aggregation": aggregation,
                "alias": alias,
            }
        )
    return normalized


def _normalize_order_by(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        raise IntentExtractionModelOutputError("Expected list for order_by.")

    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        column = str(item.get("column", "")).strip()
        if not column:
            continue
        direction = str(item.get("direction", "ASC")).strip().upper() or "ASC"
        if direction not in {"ASC", "DESC"}:
            direction = "ASC"
        normalized.append({"column": column, "direction": direction})
    return normalized


def _normalize_limit(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _as_metric_specs_from_columns(metrics: list[str], aggregation: str | None) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for metric in metrics:
        metric_clean = str(metric).strip()
        if not metric_clean:
            continue
        specs.append(
            {
                "column": metric_clean,
                "aggregation": aggregation if aggregation in {"SUM", "AVG", "COUNT", "MIN", "MAX"} else None,
                "alias": None,
            }
        )
    return specs


def _is_relationship_query(query: str) -> bool:
    lowered = str(query or "").strip().lower()
    if not lowered:
        return False
    if any(keyword in lowered for keyword in _RELATIONSHIP_KEYWORDS):
        return True
    return bool(re.search(r"\bbetween\b.+\band\b", lowered))


def _relationship_ready_metrics(
    *,
    candidates: list[str],
    schema: dict[str, list[dict[str, Any]]],
) -> list[str]:
    numeric_columns: set[str] = set()
    for columns in schema.values():
        for col in columns:
            name = str(col.get("name", "")).strip()
            col_type = str(col.get("type", "")).strip().lower()
            if not name:
                continue
            if any(token in col_type for token in ("int", "float", "double", "decimal", "numeric", "real")):
                numeric_columns.add(name)

    resolved: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        metric = str(candidate or "").strip()
        if not metric:
            continue
        metric_lower = metric.lower()
        if metric_lower in seen:
            continue
        if metric in numeric_columns:
            resolved.append(metric)
            seen.add(metric_lower)
        if len(resolved) >= 2:
            break
    return resolved


def _enrich_with_semantic_ir(
    *,
    query: str,
    schema: dict[str, list[dict[str, Any]]],
    intent_payload: StructuredIntent,
) -> StructuredIntent:
    raw_intent_for_planner: dict[str, Any] = {
        "table": intent_payload.get("table", ""),
        "intent": intent_payload.get("intent", "projection"),
        "operations": intent_payload.get("operations", []),
        "metric_specs": intent_payload.get("metric_specs", []),
        "metrics": intent_payload.get("metrics", []),
        "dimensions": intent_payload.get("dimensions", []),
        "filters": intent_payload.get("filters", []),
        "order_by": intent_payload.get("order_by", []),
        "limit": intent_payload.get("limit"),
        "ranking": intent_payload.get("ranking", {}),
        "ambiguities": intent_payload.get("ambiguities", []),
    }

    try:
        normalized = normalize_analytical_intent(
            question=query,
            raw_intent=raw_intent_for_planner,
            schema=schema,
        )
    except Exception:
        return intent_payload

    normalized_metrics = normalized.get("metrics", []) or []
    enriched_metric_specs: list[dict[str, Any]] = []
    enriched_metrics: list[str] = []
    for metric in normalized_metrics:
        if not isinstance(metric, dict):
            continue
        column = str(metric.get("column", "")).strip()
        if not column:
            continue
        enriched_metrics.append(column)
        enriched_metric_specs.append(
            {
                "column": column,
                "aggregation": metric.get("aggregation"),
                "alias": metric.get("alias"),
            }
        )

    if not enriched_metrics:
        enriched_metrics = intent_payload.get("metrics", []) or []
    if not enriched_metric_specs and enriched_metrics:
        enriched_metric_specs = _as_metric_specs_from_columns(
            enriched_metrics,
            str(normalized.get("aggregation", "")).strip().upper() or None,
        )

    target_column = str(intent_payload.get("target_column", "")).strip()
    if not target_column:
        target_column = enriched_metrics[0] if enriched_metrics else "*"

    relationship_query = _is_relationship_query(query)
    normalized_operations = {
        str(op).strip().lower()
        for op in (normalized.get("operations", []) or [])
        if str(op).strip()
    }
    normalized_dimensions = [
        str(item).strip()
        for item in (normalized.get("dimensions", []) or [])
        if str(item).strip()
    ]
    has_time_like_dimension = any(
        (
            dim.lower() in {"ds", "date", "period", "timestamp", "datetime"}
            or any(token in dim.lower() for token in ("date", "time", "day", "week", "month", "quarter", "year"))
        )
        for dim in normalized_dimensions
    )
    time_grouping_detected = bool(
        normalized.get("time_grouping_detected")
        or "time_grouping" in normalized_operations
        or str(normalized.get("intent", "")).strip().lower() == "time_series"
        or has_time_like_dimension
    )
    if relationship_query and not time_grouping_detected:
        candidate_metrics: list[str] = []
        candidate_metrics.extend([str(item).strip() for item in enriched_metrics if str(item).strip()])
        candidate_metrics.extend([str(item).strip() for item in (intent_payload.get("metrics", []) or []) if str(item).strip()])
        relationship_metrics = _relationship_ready_metrics(candidates=candidate_metrics, schema=schema)
        if len(relationship_metrics) >= 2:
            return {
                "intent_type": intent_payload["intent_type"],
                "intent": "comparison",
                "metrics": relationship_metrics,
                "metric_specs": [
                    {"column": metric, "aggregation": None, "alias": None}
                    for metric in relationship_metrics
                ],
                "dimensions": [],
                "filters": normalized.get("filters", []) or [],
                "time_range": str(intent_payload.get("time_range", "all_time")).strip() or "all_time",
                "aggregation": "",
                "target_column": relationship_metrics[0],
                "table": str(normalized.get("table", intent_payload.get("table", ""))).strip(),
                "order_by": [],
                "limit": None,
                "ranking": {"direction": None, "requested": False, "source": "relationship_override"},
                "operations": ["projection", "comparison"],
                "ambiguities": normalized.get("ambiguities", []) if isinstance(normalized.get("ambiguities"), list) else [],
            }

    return {
        "intent_type": intent_payload["intent_type"],
        "intent": str(normalized.get("intent", intent_payload.get("intent", "projection"))),
        "metrics": enriched_metrics or ["*"],
        "metric_specs": enriched_metric_specs,
        "dimensions": [str(item).strip() for item in (normalized.get("dimensions", []) or []) if str(item).strip()],
        "filters": normalized.get("filters", []) or [],
        "time_range": str(intent_payload.get("time_range", "all_time")).strip() or "all_time",
        "aggregation": str(normalized.get("aggregation", intent_payload.get("aggregation", "")) or ""),
        "target_column": target_column,
        "table": str(normalized.get("table", intent_payload.get("table", ""))).strip(),
        "order_by": normalized.get("order_by", []) or [],
        "limit": normalized.get("limit"),
        "ranking": normalized.get("ranking", {}) if isinstance(normalized.get("ranking"), dict) else {},
        "operations": normalized.get("operations", []) if isinstance(normalized.get("operations"), list) else [],
        "ambiguities": normalized.get("ambiguities", []) if isinstance(normalized.get("ambiguities"), list) else [],
    }


def infer_intent_type(*, query: str, hinted_intent_type: str | None = None) -> IntentType:
    hinted = (hinted_intent_type or "").strip().lower()
    if hinted in _VALID_INTENT_TYPES:
        return hinted  # type: ignore[return-value]

    lowered = (query or "").lower()

    if any(keyword in lowered for keyword in _PREDICTIVE_KEYWORDS):
        return "predictive"

    for pattern in _FUTURE_TIME_PATTERNS:
        if re.search(pattern, lowered):
            return "predictive"

    current_year = datetime.now(timezone.utc).year
    for match in re.findall(r"\b(19\d{2}|20\d{2}|21\d{2})\b", lowered):
        if int(match) > current_year:
            return "predictive"

    return "analytical"


def _call_ollama(
    *,
    prompt: str,
    config: IntentExtractionConfig,
) -> str:
    payload = {
        "model": config.ollama_model,
        "prompt": prompt,
        "stream": False,
    }

    try:
        response = requests.post(
            config.ollama_url,
            json=payload,
            timeout=config.request_timeout_seconds,
        )
    except requests.Timeout as exc:
        raise IntentExtractionSystemError(
            f"Ollama timeout after {config.request_timeout_seconds}s."
        ) from exc
    except requests.RequestException as exc:
        raise IntentExtractionSystemError(f"Ollama request failed: {exc}") from exc

    if response.status_code in {408, 429, 500, 502, 503, 504}:
        raise IntentExtractionSystemError(
            f"Ollama transient error ({response.status_code}): {response.text.strip()}"
        )
    if response.status_code >= 400:
        raise IntentExtractionModelOutputError(
            f"Ollama returned HTTP {response.status_code}: {response.text.strip()}"
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise IntentExtractionModelOutputError("Ollama returned non-JSON body.") from exc

    content = str(body.get("response", "")).strip()
    if not content:
        raise IntentExtractionModelOutputError("Ollama returned empty content.")
    return content


def _call_openrouter(*, prompt: str) -> str:
    try:
        from llm_app.llm_client import call_llm
    except Exception as exc:  # noqa: BLE001
        raise IntentExtractionSystemError(f"LLM client import failed: {exc}") from exc

    try:
        content = call_llm(prompt)
    except ValueError as exc:
        raise IntentExtractionSystemError(f"LLM configuration error: {exc}") from exc
    except RuntimeError as exc:
        lowered = str(exc).lower()
        if "timeout" in lowered or "timed out" in lowered:
            raise IntentExtractionSystemError(str(exc)) from exc
        raise IntentExtractionSystemError(f"LLM service error: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise IntentExtractionSystemError(f"Unexpected LLM error: {exc}") from exc

    if not content or not content.strip():
        raise IntentExtractionModelOutputError("LLM returned empty content.")
    return content


def extract_structured_intent(
    *,
    query: str,
    schema: dict[str, list[dict[str, Any]]],
    config: IntentExtractionConfig,
    logger: logging.Logger,
    log_event: Callable[..., None],
    include_debug: bool = False,
) -> StructuredIntent | tuple[StructuredIntent, dict[str, Any]]:
    prompt = _build_extraction_prompt(query=query, schema=schema)
    provider = config.llm_provider

    log_event(
        logger,
        logging.INFO,
        "Calling LLM for intent extraction",
        llm_provider=provider,
        input_query_preview=query[:200],
    )

    if provider == "ollama":
        raw_output = _call_ollama(prompt=prompt, config=config)
    else:
        raw_output = _call_openrouter(prompt=prompt)

    payload = _extract_json(raw_output)

    metrics = _normalize_string_list(payload.get("metrics"))
    dimensions = _normalize_string_list(payload.get("dimensions"))
    metric_specs = _normalize_metric_specs(payload.get("metric_specs"))
    filters = _normalize_filters(payload.get("filters"))
    order_by = _normalize_order_by(payload.get("order_by"))
    limit = _normalize_limit(payload.get("limit"))
    aggregation = str(payload.get("aggregation", "SUM")).strip().upper() or "SUM"
    table = str(payload.get("table", "")).strip()
    target_column = str(payload.get("target_column", "")).strip()
    time_range = str(payload.get("time_range", "")).strip() or "all_time"

    if not target_column and metrics:
        target_column = metrics[0]

    intent_type = infer_intent_type(
        query=query,
        hinted_intent_type=str(payload.get("intent_type", "")).strip(),
    )

    intent_payload: StructuredIntent = {
        "intent_type": intent_type,
        "intent": "projection",
        "metrics": metrics,
        "metric_specs": metric_specs,
        "dimensions": dimensions,
        "filters": filters,
        "time_range": time_range,
        "aggregation": aggregation,
        "target_column": target_column,
        "table": table,
        "order_by": order_by,
        "limit": limit,
        "ranking": payload.get("ranking") if isinstance(payload.get("ranking"), dict) else {},
        "operations": payload.get("operations") if isinstance(payload.get("operations"), list) else [],
        "ambiguities": payload.get("ambiguities") if isinstance(payload.get("ambiguities"), list) else [],
    }
    intent_payload = _enrich_with_semantic_ir(
        query=query,
        schema=schema,
        intent_payload=intent_payload,
    )
    debug_payload = {
        "provider": provider,
        "prompt": prompt,
        "raw_output": raw_output,
        "parsed_payload": payload,
    }
    if include_debug:
        return intent_payload, debug_payload
    return intent_payload
