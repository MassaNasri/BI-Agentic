"""AST-backed SQL guard shared by query, voice, and report services."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Tuple

import sqlglot
from sqlglot import exp

from bi_platform_shared.sql.normalization import TABLE_REF_PATTERN, normalize_table_name

logger = logging.getLogger(__name__)


BLOCKED_STATEMENTS = {
    "ALTER",
    "ATTACH",
    "BACKUP",
    "CREATE",
    "DELETE",
    "DESCRIBE",
    "DETACH",
    "DROP",
    "EXISTS",
    "EXPLAIN",
    "GRANT",
    "INSERT",
    "KILL",
    "OPTIMIZE",
    "RENAME",
    "RESTORE",
    "REVOKE",
    "SET",
    "SHOW",
    "SYSTEM",
    "TRUNCATE",
    "UPDATE",
    "USE",
}
BLOCKED_DATABASES = {"system", "information_schema", "information_schema_tables"}
BLOCKED_TABLE_FUNCTIONS = {
    "cluster",
    "clusterallreplicas",
    "dictionary",
    "executable",
    "file",
    "generaterandom",
    "hdfs",
    "jdbc",
    "mysql",
    "numbers",
    "odbc",
    "postgresql",
    "remote",
    "s3",
    "url",
}
BLOCKED_MASKED_PATTERNS = (
    (re.compile(r"\bINTO\s+OUTFILE\b", re.IGNORECASE), "INTO OUTFILE is not allowed"),
    (re.compile(r"\bINTO\s+DUMPFILE\b", re.IGNORECASE), "INTO DUMPFILE is not allowed"),
    (re.compile(r"\bFORMAT\s+[A-Za-z0-9_]+\b", re.IGNORECASE), "Client-controlled FORMAT clauses are not allowed"),
    (re.compile(r"\bSETTINGS\b", re.IGNORECASE), "Client-controlled SETTINGS clauses are not allowed"),
)


def _mask_literals_and_comments(sql: str) -> str:
    """Mask string literals/comments so blocked words in text do not trip checks."""

    chars = list(sql)
    i = 0
    quote: str | None = None
    while i < len(chars):
        ch = chars[i]
        nxt = chars[i + 1] if i + 1 < len(chars) else ""
        if quote:
            chars[i] = " "
            if ch == "\\" and i + 1 < len(chars):
                chars[i + 1] = " "
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in {"'", '"'}:
            quote = ch
            chars[i] = " "
            i += 1
            continue
        if ch == "-" and nxt == "-":
            while i < len(chars) and chars[i] not in {"\r", "\n"}:
                chars[i] = " "
                i += 1
            continue
        if ch == "/" and nxt == "*":
            chars[i] = " "
            chars[i + 1] = " "
            i += 2
            while i < len(chars):
                end_next = chars[i + 1] if i + 1 < len(chars) else ""
                current = chars[i]
                chars[i] = " "
                if current == "*" and end_next == "/":
                    chars[i + 1] = " "
                    i += 2
                    break
                i += 1
            continue
        i += 1
    return "".join(chars)


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"--.*?$", "", sql, flags=re.MULTILINE)
    sql = re.sub(r"/\*.*?\*/", "", sql, flags=re.DOTALL)
    return sql


def _statement_name(statement: exp.Expression) -> str:
    if isinstance(statement, exp.Select):
        return "SELECT"
    if isinstance(statement, exp.Union):
        return "SELECT"
    return statement.key.upper()


def _is_readonly_select(statement: exp.Expression) -> bool:
    return isinstance(statement, (exp.Select, exp.Union))


def _cte_aliases(statement: exp.Expression) -> set[str]:
    aliases: set[str] = set()
    for cte in statement.find_all(exp.CTE):
        alias = str(cte.alias or "").strip()
        if alias:
            aliases.add(alias.lower())
    return aliases


def _table_identifier(table: exp.Table) -> tuple[str, str, str]:
    catalog = str(table.catalog or "").strip("`\"")
    db = str(table.db or "").strip("`\"")
    name = str(table.name or "").strip("`\"")
    return catalog, db, name


class SQLGuard:
    """Validate and sanitize SQL using parser/AST allowlisting."""

    def __init__(self, workspace_database: str | None = None, allowed_tables: set[str] | None = None):
        self.workspace_database = str(workspace_database or "").strip()
        self.allowed_tables = {table.lower() for table in (allowed_tables or set()) if table}

    def validate_sql(self, sql: str) -> Tuple[bool, str, Dict[str, Any]]:
        sql_clean = str(sql or "").strip()
        details: dict[str, Any] = {
            "checks_passed": [],
            "checks_failed": [],
            "tables": [],
        }
        if not sql_clean:
            return False, "SQL query is empty", details

        masked = _mask_literals_and_comments(sql_clean)
        for pattern, message in BLOCKED_MASKED_PATTERNS:
            if pattern.search(masked):
                details["checks_failed"].append(message)
                return False, message, details

        try:
            statements = sqlglot.parse(sql_clean, read="clickhouse")
        except Exception as exc:
            details["checks_failed"].append("parse_error")
            return False, f"SQL parse error: {exc}", details

        statements = [statement for statement in statements if statement is not None]
        if len(statements) != 1:
            details["checks_failed"].append("multiple_statements")
            return False, "Only one SQL statement is allowed", details

        statement = statements[0]
        statement_name = _statement_name(statement)
        if statement_name in BLOCKED_STATEMENTS or not _is_readonly_select(statement):
            details["checks_failed"].append(f"blocked_statement:{statement_name}")
            return False, f"Only SELECT/WITH queries are allowed; got {statement_name}", details
        details["checks_passed"].append("readonly_select")

        cte_aliases = _cte_aliases(statement)
        for function in statement.find_all(exp.Func):
            function_name = str(function.name or function.sql_name() or "").strip().lower()
            if function_name in BLOCKED_TABLE_FUNCTIONS:
                details["checks_failed"].append(f"blocked_function:{function_name}")
                return False, f"Blocked table/function source: {function_name}", details

        for anonymous in statement.find_all(exp.Anonymous):
            function_name = str(anonymous.name or "").strip().lower()
            if function_name in BLOCKED_TABLE_FUNCTIONS:
                details["checks_failed"].append(f"blocked_function:{function_name}")
                return False, f"Blocked table/function source: {function_name}", details

        for table in statement.find_all(exp.Table):
            _catalog, db, name = _table_identifier(table)
            if not name:
                continue
            lowered_name = name.lower()
            if lowered_name in cte_aliases:
                continue
            lowered_db = db.lower()
            details["tables"].append({"database": db, "table": name})

            if lowered_db in BLOCKED_DATABASES or lowered_name in BLOCKED_DATABASES:
                details["checks_failed"].append(f"blocked_database:{db or name}")
                return False, f"Access to database/table '{db or name}' is not allowed", details
            if self.workspace_database and lowered_db and lowered_db != self.workspace_database.lower():
                details["checks_failed"].append(f"database_mismatch:{db}")
                return False, f"database_mismatch: {db}", details
            if self.allowed_tables and lowered_name not in self.allowed_tables:
                details["checks_failed"].append(f"unauthorized_table:{name}")
                return False, f"unauthorized_table: {name}", details

        details["checks_passed"].append("workspace_isolation")
        return True, "SQL validation passed", details

    def sanitize_sql(self, sql: str) -> str:
        cleaned = _strip_comments(str(sql or ""))
        cleaned = " ".join(cleaned.split())
        return cleaned.strip()

    def enforce_workspace_database(self, sql: str) -> str:
        if not self.workspace_database:
            return sql
        try:
            statement = sqlglot.parse_one(sql, read="clickhouse")
            cte_aliases = _cte_aliases(statement)
        except Exception:
            cte_aliases = set()

        def _replace(match: re.Match[str]) -> str:
            clause = match.group(1)
            raw_table = match.group(2)
            clean_table = raw_table.replace("`", "")
            if clean_table.lower() in cte_aliases:
                return match.group(0)
            normalized = normalize_table_name(raw_table, self.workspace_database)
            return f"{clause} {normalized}"

        return TABLE_REF_PATTERN.sub(_replace, sql)

    def validate_and_sanitize(self, sql: str) -> Tuple[bool, str, str]:
        raw_sql = str(sql or "").strip()
        is_valid, error_msg, _details = self.validate_sql(raw_sql)
        sanitized = self.sanitize_sql(raw_sql)
        if not is_valid:
            return False, error_msg, sanitized
        return True, "Validation passed", self.enforce_workspace_database(sanitized)


class SQLGuardFactory:
    """Factory for creating SQL guards with workspace isolation."""

    @staticmethod
    def create_for_workspace(workspace):
        workspace_database = getattr(workspace, "clickhouse_database", "") or getattr(workspace, "database", "") or "etl"
        return SQLGuard(workspace_database=workspace_database)

    @staticmethod
    def create_default():
        return SQLGuard()


def validate_sql(sql: str, workspace=None) -> Tuple[bool, str]:
    guard = SQLGuardFactory.create_for_workspace(workspace) if workspace else SQLGuardFactory.create_default()
    is_valid, error_msg, _ = guard.validate_and_sanitize(sql)
    return is_valid, error_msg


def sanitize_and_validate_sql(sql: str, workspace=None) -> Tuple[bool, str, str]:
    guard = SQLGuardFactory.create_for_workspace(workspace) if workspace else SQLGuardFactory.create_default()
    return guard.validate_and_sanitize(sql)


__all__ = [
    "SQLGuard",
    "SQLGuardFactory",
    "sanitize_and_validate_sql",
    "validate_sql",
]
