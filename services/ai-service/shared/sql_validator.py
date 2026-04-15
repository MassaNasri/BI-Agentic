from __future__ import annotations

import re


_FORBIDDEN_KEYWORDS = {
    "DELETE",
    "DROP",
    "UPDATE",
    "INSERT",
    "ALTER",
    "TRUNCATE",
    "CREATE",
    "REPLACE",
    "MERGE",
    "GRANT",
    "REVOKE",
}
_ALLOWED_START_PATTERN = re.compile(r"^\s*(SELECT|WITH)\b", flags=re.IGNORECASE)


def _count_semicolons(sql: str) -> int:
    # Keep this simple and deterministic for analytical SQL contracts.
    return sql.count(";")


def validate_sql(sql: str) -> None:
    normalized = str(sql or "").strip()
    if not normalized:
        raise ValueError("SQL is empty.")

    if not _ALLOWED_START_PATTERN.search(normalized):
        raise ValueError("Only read-only SELECT/CTE SQL is allowed.")

    semicolon_count = _count_semicolons(normalized)
    if semicolon_count > 1:
        raise ValueError("Multiple SQL statements are not allowed.")
    if semicolon_count == 1 and not normalized.endswith(";"):
        raise ValueError("Semicolon is only allowed at the end of the SQL statement.")

    upper = normalized.upper()
    for keyword in _FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", upper):
            raise ValueError(f"Forbidden SQL operation detected: {keyword}")
