"""
Shared ClickHouse identifier sanitization and quoting utilities.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List


_INVALID_CHARS_RE = re.compile(r"[^a-zA-Z0-9_]")
_MULTI_UNDERSCORE_RE = re.compile(r"_+")


def sanitize_identifier(name: str, prefix: str = "c", fallback: str = "column") -> str:
    """
    Sanitize an arbitrary identifier into a ClickHouse-safe identifier token.
    """
    value = str(name or "").strip()
    if not value:
        value = fallback

    safe = _INVALID_CHARS_RE.sub("_", value)
    safe = _MULTI_UNDERSCORE_RE.sub("_", safe).strip("_")
    if not safe:
        safe = fallback
    if safe[0].isdigit():
        safe = f"{prefix}_{safe}"
    return safe


def quote_identifier(name: str) -> str:
    """
    Quote a pre-sanitized ClickHouse identifier with backticks.
    """
    escaped = str(name).replace("`", "``")
    return f"`{escaped}`"


def sanitize_column_name(name: str) -> str:
    """
    Sanitize a column identifier.
    """
    return sanitize_identifier(name, prefix="c", fallback="column")


def sanitize_table_name(name: str) -> str:
    """
    Sanitize a table identifier. Supports optional dotted db.table names.
    """
    value = str(name or "").strip()
    if not value:
        raise ValueError("Table name is required")

    parts = [part for part in value.split(".") if part]
    if not parts:
        raise ValueError("Table name is required")
    return ".".join(sanitize_identifier(part, prefix="t", fallback="table") for part in parts)


def quote_table_name(name: str) -> str:
    """
    Sanitize and quote a table identifier (supports dotted db.table).
    """
    safe_name = sanitize_table_name(name)
    return ".".join(quote_identifier(part) for part in safe_name.split("."))


def sanitize_identifier_map(
    names: Iterable[str],
    prefix: str = "c",
    fallback: str = "column",
) -> Dict[str, str]:
    """
    Build a stable original->safe mapping with collision handling.
    """
    mapping: Dict[str, str] = {}
    used: set[str] = set()
    for original in names:
        key = str(original)
        if key in mapping:
            continue
        base = sanitize_identifier(key, prefix=prefix, fallback=fallback)
        candidate = base
        suffix = 1
        while candidate in used:
            suffix += 1
            candidate = f"{base}_{suffix}"
        mapping[key] = candidate
        used.add(candidate)
    return mapping


def normalize_row_columns(row: Dict[str, object], mapping: Dict[str, str]) -> Dict[str, object]:
    """
    Apply an original->safe mapping to one row.
    """
    normalized: Dict[str, object] = {}
    for key, value in row.items():
        normalized[mapping[str(key)]] = value
    return normalized


def quote_columns(columns: List[str]) -> str:
    """
    Return a comma-separated quoted column list.
    """
    return ", ".join(quote_identifier(c) for c in columns)
