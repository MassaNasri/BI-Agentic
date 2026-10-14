from __future__ import annotations

import sys
from pathlib import Path

def _resolve_repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in (current.parent, *current.parents):
        if (candidate / "bi_platform_shared").is_dir():
            return candidate
    raise RuntimeError("Could not locate repository root containing bi_platform_shared")


REPO_ROOT = _resolve_repo_root()
SERVICE_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, SERVICE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from query_api.services.sql_guard import SQLGuard  # noqa: E402


def test_select_with_blocked_words_inside_literals_and_comments_is_allowed():
    guard = SQLGuard(workspace_database="tenant_42")
    sql = "SELECT 'DROP TABLE users' AS note, amount FROM sales -- DELETE is text"

    is_valid, message, sanitized = guard.validate_and_sanitize(sql)

    assert is_valid, message
    assert "tenant_42.sales" in sanitized
    assert "--" not in sanitized
    assert "DROP TABLE users" in sanitized


def test_multiple_statements_are_rejected_even_when_first_is_select():
    guard = SQLGuard()

    is_valid, message, _sanitized = guard.validate_and_sanitize("SELECT 1; DROP TABLE sales")

    assert is_valid is False
    assert "Only one SQL statement" in message


def test_non_select_statements_are_rejected_by_ast():
    guard = SQLGuard()

    for sql in (
        "INSERT INTO sales VALUES (1)",
        "UPDATE sales SET amount = 0",
        "DELETE FROM sales",
        "DROP TABLE sales",
        "ALTER TABLE sales ADD COLUMN secret String",
        "CREATE TABLE stolen (id UInt64) ENGINE = Memory",
        "TRUNCATE TABLE sales",
        "SHOW TABLES",
    ):
        is_valid, message, _sanitized = guard.validate_and_sanitize(sql)
        assert is_valid is False
        assert "Only SELECT/WITH queries are allowed" in message


def test_system_database_access_is_blocked():
    guard = SQLGuard()

    is_valid, message, _sanitized = guard.validate_and_sanitize("SELECT * FROM system.tables")

    assert is_valid is False
    assert "not allowed" in message


def test_table_functions_are_blocked():
    guard = SQLGuard()

    for sql in (
        "SELECT * FROM s3('https://example.com/file.csv')",
        "SELECT * FROM merge('etl', '.*')",
        "SELECT * FROM futureUnknownTableFunction('tenant-data')",
        "SELECT dictGet('tenant_dictionary', 'secret', 1)",
        "SELECT joinGet('tenant_join', 'secret', 1)",
    ):
        is_valid, message, _sanitized = guard.validate_and_sanitize(sql)
        assert is_valid is False
        assert "Blocked table/function source" in message


def test_workspace_database_is_enforced_and_cte_aliases_are_not_rewritten():
    guard = SQLGuard(workspace_database="tenant_42")
    sql = "WITH recent AS (SELECT * FROM sales) SELECT * FROM recent JOIN customers ON recent.customer_id = customers.id"

    is_valid, message, sanitized = guard.validate_and_sanitize(sql)

    assert is_valid, message
    assert "FROM tenant_42.sales" in sanitized
    assert "FROM recent" in sanitized
    assert "FROM tenant_42.recent" not in sanitized
    assert "JOIN tenant_42.customers" in sanitized


def test_cross_workspace_database_reference_is_rejected():
    guard = SQLGuard(workspace_database="tenant_42")

    is_valid, message, _sanitized = guard.validate_and_sanitize("SELECT * FROM other_workspace.sales")

    assert is_valid is False
    assert "database_mismatch" in message


def test_mixed_quoted_qualified_table_is_preserved_as_two_identifiers():
    guard = SQLGuard(workspace_database="etl")

    is_valid, message, sanitized = guard.validate_and_sanitize(
        "SELECT * FROM etl.`p0c_sales_abc_csv`"
    )

    assert is_valid, message
    assert sanitized == "SELECT * FROM etl.p0c_sales_abc_csv"


def test_individually_quoted_qualified_table_is_not_wrapped_as_one_identifier():
    guard = SQLGuard(workspace_database="etl")

    is_valid, message, sanitized = guard.validate_and_sanitize(
        "SELECT * FROM `etl`.`sales`"
    )

    assert is_valid, message
    assert sanitized == "SELECT * FROM etl.sales"


def test_product_guard_requires_non_empty_table_binding():
    guard = SQLGuard(
        workspace_database="etl",
        allowed_tables=set(),
        require_allowed_tables=True,
    )

    is_valid, message, _sanitized = guard.validate_and_sanitize("SELECT * FROM sales")

    assert is_valid is False
    assert message.startswith("allowed_tables_required")


def test_exact_allowlist_handles_quotes_aliases_joins_ctes_and_subqueries():
    guard = SQLGuard(
        workspace_database="etl",
        allowed_tables={"sales", "customers"},
        require_allowed_tables=True,
    )
    valid_sql = (
        'WITH recent AS (SELECT * FROM `etl`.`sales`) '
        'SELECT c.id FROM recent r JOIN "customers" c ON r.customer_id = c.id '
        'WHERE c.id IN (SELECT customer_id FROM sales)'
    )

    is_valid, message, _sanitized = guard.validate_and_sanitize(valid_sql)
    assert is_valid, message

    bypasses = (
        "SELECT * FROM secret",
        "SELECT * FROM etl.secret",
        "SELECT * FROM sales JOIN secret ON sales.id = secret.id",
        "SELECT * FROM sales WHERE id IN (SELECT id FROM secret)",
        "WITH hidden AS (SELECT * FROM secret) SELECT * FROM hidden",
        'SELECT * FROM `secret`',
    )
    for sql in bypasses:
        is_valid, message, _sanitized = guard.validate_and_sanitize(sql)
        assert is_valid is False
        assert message.startswith("unauthorized_table")
