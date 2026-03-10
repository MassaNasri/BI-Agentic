import re


# Matches basic FROM/JOIN table references in SELECT queries.
TABLE_REF_PATTERN = re.compile(
    r"\b(FROM|JOIN)\s+(`?[A-Za-z_][A-Za-z0-9_\.]*`?)",
    flags=re.IGNORECASE,
)


def normalize_table_name(table_name: str, default_db: str) -> str:
    """
    Normalize table names to ClickHouse-safe form.

    Rules:
    - no dot -> default_db.table
    - exactly one dot -> keep as is
    - multiple dots -> keep only the last two parts
    """
    if not table_name or not table_name.strip():
        raise ValueError("table_name must be a non-empty string")
    if not default_db or not default_db.strip():
        raise ValueError("default_db must be a non-empty string")

    cleaned = table_name.strip().strip("`")
    parts = [part for part in cleaned.split(".") if part]

    if len(parts) == 1:
        normalized = f"{default_db}.{parts[0]}"
    elif len(parts) == 2:
        normalized = f"{parts[0]}.{parts[1]}"
    else:
        normalized = f"{parts[-2]}.{parts[-1]}"

    return normalized


def normalize_sql_table_references(sql: str, default_db: str) -> str:
    """
    Normalize table references in FROM/JOIN clauses.
    """
    if not sql or not sql.strip():
        return sql

    def _replace(match: re.Match) -> str:
        clause = match.group(1)
        raw_table = match.group(2)
        quote = "`" if raw_table.startswith("`") and raw_table.endswith("`") else ""
        normalized = normalize_table_name(raw_table.strip("`"), default_db)
        if quote:
            normalized = f"`{normalized}`"
        return f"{clause} {normalized}"

    return TABLE_REF_PATTERN.sub(_replace, sql)
