"""
Database type normalization helpers used across ETL services.
"""
from __future__ import annotations

from typing import Optional


_DB_TYPE_ALIASES = {
    "mysql": "mysql",
    "mariadb": "mysql",
    "postgres": "postgres",
    "postgresql": "postgres",
    "psql": "postgres",
    "sqlite": "sqlite",
    "sqlite3": "sqlite",
    "mssql": "mssql",
    "sqlserver": "mssql",
    "sql_server": "mssql",
    "oracle": "oracle",
}

_CANONICAL_DB_TYPES = ("mysql", "postgres", "sqlite", "mssql", "oracle")


def canonical_db_types() -> tuple[str, ...]:
    """
    Return the canonical database type vocabulary used by the platform.
    """
    return _CANONICAL_DB_TYPES


def normalize_db_type(db_type: Optional[str]) -> Optional[str]:
    """
    Normalize a user/service-provided DB type into the canonical vocabulary.

    Returns None when the value is not recognized.
    """
    if db_type is None:
        return None
    normalized = str(db_type).strip().lower()
    if not normalized:
        return None
    return _DB_TYPE_ALIASES.get(normalized)

