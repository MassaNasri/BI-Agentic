from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import requests

from shared.sql_validator import validate_sql


_TOP_N_PATTERN = re.compile(r"\b(top|bottom)\s+(\d+)\b", flags=re.IGNORECASE)
_GROUPING_PATTERN = re.compile(r"\b(by|per|across|for each|in each)\b", flags=re.IGNORECASE)
_AGGREGATION_PATTERN = re.compile(r"\b(sum|avg|average|count|min|max|total)\b", flags=re.IGNORECASE)
_LIMIT_PATTERN = re.compile(r"\bLIMIT\s+(\d+)\b", flags=re.IGNORECASE)
_ORDER_PATTERN = re.compile(r"\bORDER\s+BY\b", flags=re.IGNORECASE)
_GROUP_BY_PATTERN = re.compile(r"\bGROUP\s+BY\b", flags=re.IGNORECASE)
_FROM_PATTERN = re.compile(r"\bFROM\s+([a-zA-Z0-9_.]+)\b", flags=re.IGNORECASE)


@dataclass(frozen=True)
class SqlReviewConfig:
    provider: str
    ollama_url: str
    ollama_model: str
    timeout_seconds: float
    enabled: bool

    @classmethod
    def from_env(cls) -> "SqlReviewConfig":
        return cls(
            provider=os.getenv("SQL_REVIEW_PROVIDER", "openrouter").strip().lower(),
            ollama_url=os.getenv("SQL_REVIEW_OLLAMA_URL", "http://localhost:11434/api/generate").strip(),
            ollama_model=os.getenv("SQL_REVIEW_OLLAMA_MODEL", "gemma3:1b").strip(),
            timeout_seconds=float(os.getenv("SQL_REVIEW_TIMEOUT_SECONDS", "20") or "20"),
            enabled=str(os.getenv("SQL_REVIEW_ENABLED", "true")).strip().lower() not in {"0", "false", "no"},
        )


def _schema_to_prompt(schema: dict[str, list[dict[str, Any]]]) -> str:
    rows: list[str] = []
    for table_name, columns in schema.items():
        rows.append(f"Table: {table_name}")
        for column in columns:
            rows.append(f"- {column.get('name', '')} ({column.get('type', '')})")
    return "\n".join(rows)


def _build_review_prompt(
    *,
    question: str,
    schema: dict[str, list[dict[str, Any]]],
    generated_sql: str,
    validated_intent: dict[str, Any] | None,
    extracted_intent: dict[str, Any] | None,
) -> str:
    return (
        "You are a SQL review and correction engine for BI analytics.\n"
        "Task: verify whether SQL answers the user question using the provided schema.\n"
        "You may correct SQL, but must keep semantics aligned with the question.\n\n"
        "STRICT SAFETY RULES (NON-NEGOTIABLE):\n"
        "- You must produce READ-ONLY SQL only.\n"
        "- Allowed query style: SELECT or WITH ... SELECT.\n"
        "- Forbidden: DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE, CREATE, REPLACE, MERGE, GRANT, REVOKE.\n"
        "- Never output multiple statements.\n\n"
        "Return JSON only with this exact shape:\n"
        "{\n"
        '  "status": "approved|corrected|rejected",\n'
        '  "sql": "single SQL statement",\n'
        '  "reason_category": "alignment|schema|safety|syntax|other",\n'
        '  "notes": ["short note 1", "short note 2"]\n'
        "}\n\n"
        f"User question:\n{question}\n\n"
        f"Schema:\n{_schema_to_prompt(schema)}\n\n"
        f"Extracted intent:\n{json.dumps(extracted_intent or {}, ensure_ascii=True)}\n\n"
        f"Validated intent:\n{json.dumps(validated_intent or {}, ensure_ascii=True)}\n\n"
        f"Generated SQL:\n{generated_sql}\n\n"
        "JSON response:"
    )


def _parse_json_payload(raw_output: str) -> dict[str, Any]:
    if not raw_output:
        raise ValueError("SQL review model returned empty output")
    start = raw_output.find("{")
    end = raw_output.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("SQL review model did not return JSON")
    parsed = json.loads(raw_output[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("SQL review model returned invalid JSON object")
    return parsed


def _call_openrouter(prompt: str) -> str:
    from llm_app.llm_client import call_llm

    return call_llm(prompt)


def _call_ollama(prompt: str, config: SqlReviewConfig) -> str:
    response = requests.post(
        config.ollama_url,
        json={"model": config.ollama_model, "prompt": prompt, "stream": False},
        timeout=config.timeout_seconds,
    )
    response.raise_for_status()
    body = response.json()
    return str(body.get("response", "")).strip()


def _deterministic_review(question: str, generated_sql: str) -> dict[str, Any]:
    sql = str(generated_sql or "").strip()
    if not sql:
        return {
            "status": "rejected",
            "sql": "",
            "reason_category": "syntax",
            "notes": ["Generated SQL is empty."],
        }

    notes: list[str] = []
    question_lower = question.lower()
    sql_upper = sql.upper()
    match = _TOP_N_PATTERN.search(question_lower)
    if match:
        expected_limit = int(match.group(2))
        limit_match = _LIMIT_PATTERN.search(sql_upper)
        if not limit_match:
            notes.append(f"Expected LIMIT {expected_limit} for top/bottom request.")
        elif int(limit_match.group(1)) != expected_limit:
            notes.append(f"LIMIT mismatch: expected {expected_limit}.")
        if not _ORDER_PATTERN.search(sql_upper):
            notes.append("Top/bottom request should include ORDER BY.")

    if _AGGREGATION_PATTERN.search(question_lower) and _GROUPING_PATTERN.search(question_lower):
        if not _GROUP_BY_PATTERN.search(sql_upper):
            notes.append("Grouped analytical question should include GROUP BY.")

    if notes:
        return {
            "status": "rejected",
            "sql": sql,
            "reason_category": "alignment",
            "notes": notes,
        }
    return {
        "status": "approved",
        "sql": sql,
        "reason_category": "alignment",
        "notes": ["Deterministic SQL review passed."],
    }


def _sql_mentions_token(sql_upper: str, token: str) -> bool:
    token_upper = str(token or "").strip().upper()
    if not token_upper:
        return False
    return re.search(rf"\b{re.escape(token_upper)}\b", sql_upper) is not None


def _validate_sql_against_intent(sql: str, validated_intent: dict[str, Any] | None) -> list[str]:
    if not validated_intent or not isinstance(validated_intent, dict):
        return []

    notes: list[str] = []
    sql_upper = str(sql or "").upper()

    expected_table = str(validated_intent.get("table", "")).strip()
    from_match = _FROM_PATTERN.search(sql)
    if expected_table and from_match:
        actual_from = from_match.group(1).strip()
        expected_candidates = {expected_table.lower(), expected_table.split(".")[-1].lower()}
        actual_candidates = {actual_from.lower(), actual_from.split(".")[-1].lower()}
        if expected_candidates.isdisjoint(actual_candidates):
            notes.append(f"Reviewed SQL changed target table from '{expected_table}' to '{actual_from}'.")

    order_by = validated_intent.get("order_by") or []
    if order_by:
        if not _ORDER_PATTERN.search(sql_upper):
            notes.append("Reviewed SQL dropped ORDER BY required by intent.")
        for order_item in order_by:
            if not isinstance(order_item, dict):
                continue
            column = str(order_item.get("column", "")).strip()
            if column and not _sql_mentions_token(sql_upper, column):
                notes.append(f"Reviewed SQL is missing ORDER BY reference '{column}'.")

    limit = validated_intent.get("limit")
    if isinstance(limit, int) and limit > 0:
        limit_match = _LIMIT_PATTERN.search(sql_upper)
        if not limit_match:
            notes.append(f"Reviewed SQL dropped LIMIT {limit} required by intent.")
        elif int(limit_match.group(1)) != limit:
            notes.append(f"Reviewed SQL changed LIMIT from {limit} to {limit_match.group(1)}.")

    metrics = validated_intent.get("metrics") or []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        alias = str(metric.get("alias", "")).strip()
        column = str(metric.get("column", "")).strip()
        if alias and _sql_mentions_token(sql_upper, alias):
            continue
        if column and column != "*" and not _sql_mentions_token(sql_upper, column):
            notes.append(f"Reviewed SQL is missing metric reference '{column}'.")

    filters = validated_intent.get("filters") or []
    for filter_item in filters:
        if not isinstance(filter_item, dict):
            continue
        column = str(filter_item.get("column", "")).strip()
        if column and not _sql_mentions_token(sql_upper, column):
            notes.append(f"Reviewed SQL is missing filter reference '{column}'.")

    dimensions = [str(dim).strip() for dim in (validated_intent.get("dimensions") or []) if str(dim).strip()]
    has_aggregated_metric = any(
        isinstance(metric, dict) and str(metric.get("aggregation", "")).strip()
        for metric in metrics
    )
    if dimensions and has_aggregated_metric:
        if not _GROUP_BY_PATTERN.search(sql_upper):
            notes.append("Reviewed SQL dropped GROUP BY required by grouped intent.")
        for dimension in dimensions:
            if not _sql_mentions_token(sql_upper, dimension):
                notes.append(f"Reviewed SQL is missing grouped dimension '{dimension}'.")

    return notes


def review_and_correct_sql(
    *,
    question: str,
    schema: dict[str, list[dict[str, Any]]],
    generated_sql: str,
    validated_intent: dict[str, Any] | None = None,
    extracted_intent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = SqlReviewConfig.from_env()
    deterministic_result = _deterministic_review(question=question, generated_sql=generated_sql)

    if not config.enabled:
        final_sql = str(deterministic_result.get("sql", generated_sql)).strip()
        validate_sql(final_sql)
        alignment_notes = _validate_sql_against_intent(final_sql, validated_intent)
        status = deterministic_result.get("status", "approved")
        notes = list(deterministic_result.get("notes", []))
        if alignment_notes:
            final_sql = str(generated_sql or "").strip()
            validate_sql(final_sql)
            status = "approved"
            notes.extend(alignment_notes)
            notes.append("Review SQL reset to compiler output to preserve IR semantics.")
        return {
            "status": status,
            "generated_sql": generated_sql,
            "reviewed_sql": final_sql,
            "reason_category": deterministic_result.get("reason_category", "alignment"),
            "notes": notes,
            "model_provider": "disabled",
            "llm_used": False,
        }

    prompt = _build_review_prompt(
        question=question,
        schema=schema,
        generated_sql=generated_sql,
        validated_intent=validated_intent,
        extracted_intent=extracted_intent,
    )
    llm_error = ""
    llm_payload: dict[str, Any] | None = None

    try:
        if config.provider == "ollama":
            llm_raw = _call_ollama(prompt, config)
        else:
            llm_raw = _call_openrouter(prompt)
        llm_payload = _parse_json_payload(llm_raw)
    except Exception as exc:  # noqa: BLE001
        llm_error = str(exc)

    if llm_payload is None:
        final_sql = str(deterministic_result.get("sql", generated_sql)).strip()
        validate_sql(final_sql)
        alignment_notes = _validate_sql_against_intent(final_sql, validated_intent)
        if alignment_notes:
            final_sql = str(generated_sql or "").strip()
            validate_sql(final_sql)
        return {
            "status": deterministic_result.get("status", "approved"),
            "generated_sql": generated_sql,
            "reviewed_sql": final_sql,
            "reason_category": deterministic_result.get("reason_category", "alignment"),
            "notes": (
                list(deterministic_result.get("notes", []))
                + alignment_notes
                + (["Review SQL reset to compiler output to preserve IR semantics."] if alignment_notes else [])
                + [f"LLM review fallback: {llm_error}"]
            ),
            "model_provider": config.provider,
            "llm_used": False,
            "llm_error": llm_error,
        }

    llm_status = str(llm_payload.get("status", "rejected")).strip().lower()
    llm_sql = str(llm_payload.get("sql", "")).strip() or generated_sql
    llm_notes = llm_payload.get("notes", [])
    if not isinstance(llm_notes, list):
        llm_notes = [str(llm_notes)]
    llm_reason = str(llm_payload.get("reason_category", "other")).strip().lower()

    if llm_status == "rejected":
        validate_sql(str(generated_sql or "").strip())
        fallback_notes = [str(note) for note in llm_notes if str(note).strip()]
        fallback_notes.append("Review rejection fallback: preserved compiler SQL to keep validated IR semantics.")
        return {
            "status": "approved",
            "generated_sql": generated_sql,
            "reviewed_sql": str(generated_sql or "").strip(),
            "reason_category": llm_reason or "alignment",
            "notes": fallback_notes,
            "model_provider": config.provider,
            "llm_used": True,
        }

    validate_sql(llm_sql)
    alignment_notes = _validate_sql_against_intent(llm_sql, validated_intent)
    if alignment_notes:
        llm_sql = str(generated_sql or "").strip()
        validate_sql(llm_sql)
        llm_notes = [str(note) for note in llm_notes if str(note).strip()] + alignment_notes + [
            "LLM correction was overridden to preserve IR semantics."
        ]
        llm_status = "approved"
    return {
        "status": llm_status if llm_status in {"approved", "corrected", "rejected"} else "rejected",
        "generated_sql": generated_sql,
        "reviewed_sql": llm_sql,
        "reason_category": llm_reason,
        "notes": [str(note) for note in llm_notes if str(note).strip()],
        "model_provider": config.provider,
        "llm_used": True,
    }
