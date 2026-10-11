"""Compatibility wrapper for the shared AST-backed SQL guard."""

from bi_platform_shared.sql.guard import (
    SQLGuard,
    SQLGuardFactory,
    sanitize_and_validate_sql,
    validate_sql,
)

__all__ = [
    "SQLGuard",
    "SQLGuardFactory",
    "sanitize_and_validate_sql",
    "validate_sql",
]
