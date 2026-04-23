from __future__ import annotations

import re
from typing import Any

from shared.schema_utils import tokenize


_TECHNICAL_TABLE_PATTERNS = (
    r"^system$",
    r"^information_schema$",
    r"^pg_",
    r"^tmp_",
    r"_tmp$",
    r"_temp$",
    r"_staging$",
    r"_stage$",
    r"_log$",
    r"_logs$",
    r"_audit$",
    r"_registry$",
    r"_metadata$",
    r"_quarantine$",
    r"_quality$",
    r"_metrics$",
    r"_lineage$",
    r"_trace$",
    r"^quarantine_",
    r"^metadata_",
    r"^registry_",
    r"^quality_",
    r"^audit_",
    r"^lineage_",
)

_TECHNICAL_COLUMN_HINTS = {
    "_cleaned_at",
    "_processed_at",
    "_ingested_at",
    "_loaded_at",
    "_batch_id",
    "_updated_at",
    "_created_at",
    "_source_file",
    "_source_table",
    "_lineage",
    "_quality_score",
    "_quarantine_reason",
}


def _normalized_table_name(table_name: str) -> str:
    return str(table_name or "").strip().split(".")[-1].lower()


def is_technical_table_name(table_name: str) -> bool:
    normalized = _normalized_table_name(table_name)
    if not normalized:
        return True
    return any(re.search(pattern, normalized) for pattern in _TECHNICAL_TABLE_PATTERNS)


def _technical_column_count(columns: list[dict[str, Any]]) -> int:
    score = 0
    for column in columns:
        col_name = str(column.get("name", "")).strip().lower()
        if not col_name:
            continue
        if col_name in _TECHNICAL_COLUMN_HINTS:
            score += 2
        elif col_name.startswith("_"):
            score += 1
    return score


def filter_business_schema(
    schema: dict[str, list[dict[str, Any]]],
    *,
    keep_tables: set[str] | None = None,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    if not isinstance(schema, dict) or not schema:
        return {}, {"dropped_tables": [], "kept_tables": []}

    keep_tables = {str(table).strip().lower() for table in (keep_tables or set()) if str(table).strip()}
    kept: dict[str, list[dict[str, Any]]] = {}
    dropped: list[str] = []

    for table_name, columns in schema.items():
        normalized_table = str(table_name).strip()
        if not normalized_table or not isinstance(columns, list):
            continue

        table_key = normalized_table.lower()
        if table_key in keep_tables:
            kept[normalized_table] = columns
            continue

        technical_name = is_technical_table_name(normalized_table)
        technical_columns = _technical_column_count(columns)
        mostly_technical_columns = technical_columns >= max(2, len(columns) // 2)

        if technical_name or mostly_technical_columns:
            dropped.append(normalized_table)
            continue

        kept[normalized_table] = columns

    if not kept:
        # Never return an empty schema after filtering; preserve original for safety.
        return schema, {"dropped_tables": [], "kept_tables": list(schema.keys()), "filter_disabled": "no_business_tables"}

    return kept, {"dropped_tables": dropped, "kept_tables": list(kept.keys())}


def rank_tables_for_question(
    *,
    schema: dict[str, list[dict[str, Any]]],
    question: str,
    limit: int = 3,
    preferred_tables: list[str] | None = None,
) -> list[str]:
    if not isinstance(schema, dict) or not schema:
        return []

    preferred = {str(table).strip().lower() for table in (preferred_tables or []) if str(table).strip()}
    question_tokens = tokenize(question)
    ranked: list[tuple[int, str]] = []

    for table_name, columns in schema.items():
        table = str(table_name).strip()
        if not table:
            continue

        score = 0
        table_tokens = tokenize(_normalized_table_name(table))
        score += len(table_tokens & question_tokens) * 3

        if table.lower() in preferred:
            score += 8

        for column in columns if isinstance(columns, list) else []:
            col_name = str(column.get("name", "")).strip()
            if not col_name:
                continue
            score += len(tokenize(col_name) & question_tokens)

        ranked.append((score, table))

    ranked.sort(key=lambda item: item[0], reverse=True)
    selected = [table for score, table in ranked if score > 0]
    if selected:
        return selected[: max(1, int(limit))]

    # If question did not match anything, keep deterministic top N by name.
    return sorted(schema.keys())[: max(1, int(limit))]
