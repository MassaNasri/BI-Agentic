"""
ClickHouse Executor

Executes validated SQL queries on ClickHouse.
Returns results for visualization.
"""

import os
import logging
import math
import re
from typing import Dict, List, Optional, Any

try:
    import clickhouse_connect
except ModuleNotFoundError:  # pragma: no cover - depends on runtime environment
    clickhouse_connect = None

from bi_platform_shared.contracts.query import build_column_metadata
from query_api.utils import normalize_sql_table_references
from .result_shape_analyzer import analyze_result_shape

logger = logging.getLogger(__name__)


def _normalize_invalid_casts(sql: str) -> str:
    """
    Global fix: Replace invalid ClickHouse functions with valid ones.
    toFloat64OrNullOrNull / toInt64OrNullOrNull do NOT exist in ClickHouse.
    Applied at execution time so ALL queries (including those bypassing the compiler) are safe.
    """
    if not sql:
        return sql
    sql = sql.replace("toFloat64OrNullOrNull(", "toFloat64OrNull(")
    sql = sql.replace("toInt64OrNullOrNull(", "toInt64OrNull(")
    return sql


_SIMPLE_TODATE_PATTERN = re.compile(
    r"\btoDate\s*\(\s*([A-Za-z_][A-Za-z0-9_\.]*)\s*\)",
    flags=re.IGNORECASE,
)


def _is_clickhouse_date_parse_error(error_msg: str) -> bool:
    """Return True when ClickHouse reports a date parsing failure."""
    text = str(error_msg or "").lower()
    return (
        "cannot_parse_date" in text
        or "cannot parse date" in text
        or "cannot parse date from string" in text
    )


def _rewrite_todate_for_ambiguous_strings(sql: str) -> str:
    """
    Rewrite simple toDate(column) calls into a safer parser form.

    This intentionally matches only simple identifiers (e.g. ds, t.ds) to avoid
    changing complex expressions in unexpected ways.
    """
    if not sql:
        return sql

    def _replace(match: re.Match[str]) -> str:
        column_expr = match.group(1).strip()
        return (
            "toDate("
            "parseDateTimeBestEffortUSOrNull("
            f"toString({column_expr})"
            ")"
            ")"
        )

    return _SIMPLE_TODATE_PATTERN.sub(_replace, sql)


def sanitize_sql_for_http(sql: str) -> str:
    """
    Sanitize SQL for ClickHouse HTTP execution.
    
    Removes incompatible syntax:
    - FORMAT Native (not supported via HTTP)
    - Semicolons (causes multi-statement errors)
    - Invalid cast functions (toFloat64OrNullOrNull â†’ toFloat64OrNull)
    - Extra whitespace
    
    Args:
        sql: Raw SQL string (possibly from LLM)
    
    Returns:
        Clean SQL safe for HTTP execution
    """
    if not sql:
        return ""

    # Global fix: normalize invalid ClickHouse cast functions
    sql = _normalize_invalid_casts(sql)

    # Remove FORMAT Native (case-insensitive)
    clean_sql = re.sub(r'\s+FORMAT\s+Native\s*', ' ', sql, flags=re.IGNORECASE)

    # Remove all semicolons
    clean_sql = clean_sql.replace(';', '')

    # Remove extra whitespace and trim
    clean_sql = ' '.join(clean_sql.split())
    clean_sql = clean_sql.strip()

    return clean_sql


def sanitize_numeric_value(value: Any) -> Any:
    """
    ðŸ”’ NaN-SAFE: Sanitize a single numeric value to ensure JSON compatibility.
    
    Replaces NaN, Infinity, and -Infinity with 0 (or None for NULL).
    This ensures values can be safely stored in PostgreSQL JSON/JSONB fields
    and serialized to JSON without errors.
    
    Handles all numeric types including:
    - Python float, int
    - Decimal (from ClickHouse Decimal types)
    - numpy.float64, numpy.float32 (if numpy is used)
    - Any other numeric type that can be converted to float
    
    Args:
        value: Any value (numeric, string, None, etc.)
    
    Returns:
        Sanitized value (NaN/Infinity â†’ 0, None â†’ None, other values unchanged)
    """
    # Handle None/NULL
    if value is None:
        return None
    
    # Handle Python int - never NaN/Infinity, return as-is
    if isinstance(value, int):
        return value
    
    # Handle float types (NaN, Infinity) - direct check
    if isinstance(value, float):
        if math.isnan(value):
            return 0  # Replace NaN with 0
        elif math.isinf(value):
            return 0  # Replace Infinity/-Infinity with 0
        return value
    
    # Handle Decimal types (ClickHouse returns Decimal for Decimal/Float64 columns)
    # Decimal types can be converted to float for NaN/Infinity checking
    try:
        from decimal import Decimal
        if isinstance(value, Decimal):
            # Convert Decimal to float to check for NaN/Infinity
            # Decimal('NaN') and Decimal('Infinity') exist but are rare
            # Converting to float is the safest way to detect them
            try:
                float_val = float(value)
                if math.isnan(float_val):
                    return 0  # Replace NaN with 0
                elif math.isinf(float_val):
                    return 0  # Replace Infinity/-Infinity with 0
                # Return as float for JSON compatibility (Decimal isn't JSON serializable)
                return float_val
            except (ValueError, OverflowError, TypeError):
                # If conversion fails, return 0 as fallback
                return 0
    except ImportError:
        # Decimal not available, skip this check
        pass
    
    # Handle numpy types (if numpy is installed and used by clickhouse-connect)
    try:
        import numpy as np
        if isinstance(value, (np.floating, np.integer)):
            # Convert numpy numeric types to Python float for NaN/Infinity checking
            float_val = float(value)
            if math.isnan(float_val):
                return 0  # Replace NaN with 0
            elif math.isinf(float_val):
                return 0  # Replace Infinity/-Infinity with 0
            # Convert numpy types to Python native types for JSON serialization
            if isinstance(value, np.integer):
                return int(value)
            return float_val
    except (ImportError, ValueError, OverflowError, TypeError):
        # numpy not available or conversion failed, continue to generic check
        pass
    
    # Generic fallback: Try to convert any numeric-like value to float
    # This catches edge cases where ClickHouse returns unusual numeric types
    try:
        # Only attempt conversion if value looks numeric (not strings, lists, etc.)
        if not isinstance(value, (str, bytes, list, dict, tuple, bool)):
            float_val = float(value)
            if math.isnan(float_val):
                return 0  # Replace NaN with 0
            elif math.isinf(float_val):
                return 0  # Replace Infinity/-Infinity with 0
            # If conversion succeeded and no NaN/Infinity, return original value
            # (to preserve type if it's JSON-serializable)
    except (ValueError, TypeError, OverflowError):
        # Conversion failed - value is not numeric, return as-is
        pass
    
    # For non-numeric types (strings, lists, dicts, etc.), return as-is
    return value


def sanitize_query_results(rows: List[Dict]) -> List[Dict]:
    """
    ðŸ”’ NaN-SAFE: Sanitize query results to ensure JSON compatibility.
    
    Recursively sanitizes all numeric values in result rows, replacing
    NaN, Infinity, and -Infinity with 0. This ensures results can be:
    - Safely serialized to JSON
    - Stored in PostgreSQL JSON/JSONB fields
    - Sent to frontend/Metabase without errors
    
    Args:
        rows: List of dictionaries representing query result rows
    
    Returns:
        Sanitized list of dictionaries with all NaN/Infinity values replaced
    """
    sanitized_rows = []
    
    for row in rows:
        sanitized_row = {}
        for key, value in row.items():
            # Recursively sanitize nested structures
            if isinstance(value, dict):
                sanitized_row[key] = sanitize_query_results([value])[0] if value else {}
            elif isinstance(value, list):
                sanitized_row[key] = [sanitize_numeric_value(item) for item in value]
            else:
                sanitized_row[key] = sanitize_numeric_value(value)
        sanitized_rows.append(sanitized_row)
    
    return sanitized_rows


def _column_type_to_string(column_type: Any) -> str:
    """Normalize clickhouse-connect type objects to stable strings."""

    if column_type is None:
        return ""
    name = getattr(column_type, "name", None)
    if name:
        return str(name)
    return str(column_type)


class ClickHouseExecutor:
    """
    Execute SELECT queries on ClickHouse using HTTP protocol (port 8123).
    Returns results in format suitable for Metabase/visualization.
    """
    
    def __init__(self):
        """Initialize ClickHouse executor with environment configuration."""
        if clickhouse_connect is None:
            raise RuntimeError(
                "clickhouse_connect dependency is not installed. "
                "Install query-service requirements or rebuild the query-service container image."
            )

        host = os.getenv('CLICKHOUSE_HOST', 'localhost')
        port_raw = os.getenv('CLICKHOUSE_PORT', '8123')
        username = os.getenv('CLICKHOUSE_USER', '')
        password = os.getenv('CLICKHOUSE_PASSWORD', '')
        database = os.getenv('CLICKHOUSE_DATABASE', 'default')

        try:
            port = int(port_raw)
        except ValueError as exc:
            raise RuntimeError(
                f"Invalid CLICKHOUSE_PORT value: {port_raw!r}. Expected an integer (8123)."
            ) from exc

        # Validate port for HTTP protocol
        if port == 9000:
            logger.warning(
                "CLICKHOUSE_PORT is set to 9000 (native protocol). "
                "HTTP interface requires port 8123. "
                "Update your .env file: CLICKHOUSE_PORT=8123"
            )

        logger.info("Connecting to ClickHouse: %s:%s user=%s", host, port, username)

        try:
            client = clickhouse_connect.get_client(
                host=host,
                port=port,
                username=username,
                password=password,
                database=database
            )
            version_result = client.query("SELECT version()")
            version = (
                version_result.result_rows[0][0]
                if version_result.result_rows and version_result.result_rows[0]
                else "unknown"
            )
            logger.info("ClickHouse connection verified. version=%s database=%s", version, database)
        except Exception as exc:
            error_msg = str(exc)
            logger.error(
                "ClickHouse initialization failed for %s:%s user=%s database=%s: %s",
                host,
                port,
                username,
                database,
                error_msg
            )
            if 'AUTHENTICATION_FAILED' in error_msg or 'Authentication failed' in error_msg:
                raise RuntimeError(
                    "ClickHouse authentication failed. Verify CLICKHOUSE_USER, CLICKHOUSE_PASSWORD, "
                    "and CLICKHOUSE_DATABASE values. "
                    f"Loaded config host={host}, port={port}, user={username}, database={database}. "
                    f"Original error: {error_msg}"
                ) from exc
            raise RuntimeError(
                "ClickHouse connection initialization failed. "
                f"Loaded config host={host}, port={port}, user={username}, database={database}. "
                f"Original error: {error_msg}"
            ) from exc

        self.host = host
        self.port = port
        self.user = username
        self.password = password
        self.database = database
        self.client = client

    def execute_query(self, sql: str, workspace_database: Optional[str] = None) -> Dict:
        """
        Execute SQL query on ClickHouse.

        Args:
            sql: SQL query (must be SELECT only)
            workspace_database: Optional workspace db for SQL normalization

        Returns:
            dict: {
                'success': bool,
                'rows': list of dicts (query results),
                'columns': list of column metadata objects,
                'column_names': list of column names,
                'column_types': list of ClickHouse native types,
                'result_shape': semantic result shape metadata,
                'row_count': int,
                'execution_time_ms': int,
                'error': str (if failed)
            }
        """
        clean_sql = ""
        try:
            import time
            start_time = time.time()

            logger.error("RAW SQL BEFORE NORMALIZATION:")
            logger.error("=" * 80)
            logger.error(sql)
            logger.error("=" * 80)

            normalized_sql = sql
            normalize_db = workspace_database or self.database
            # Only normalize SELECT queries; keep admin statements unchanged.
            if sql and sql.strip().upper().startswith("SELECT"):
                normalized_sql = normalize_sql_table_references(sql, normalize_db)

            # Sanitize SQL for HTTP execution (removes FORMAT Native, semicolons)
            clean_sql = sanitize_sql_for_http(normalized_sql)

            # FINAL SQL boundary logging (mandatory)
            logger.error("FINAL SQL SENT TO CLICKHOUSE:")
            logger.error("=" * 80)
            logger.error(clean_sql)
            logger.error("=" * 80)

            def _result_to_payload(raw_result: Any, *, executed_sql: str, fallback_applied: bool = False, fallback_reason: str = "") -> Dict:
                execution_time_ms = int((time.time() - start_time) * 1000)

                rows: List[Dict[str, Any]] = []
                column_names = [str(name) for name in (getattr(raw_result, "column_names", []) or [])]
                column_types = [
                    _column_type_to_string(column_type)
                    for column_type in (getattr(raw_result, "column_types", []) or [])
                ]
                column_metadata = build_column_metadata(column_names, column_types)

                for row in raw_result.result_rows:
                    row_dict: Dict[str, Any] = {}
                    for i, col_name in enumerate(column_names):
                        row_dict[col_name] = row[i]
                    rows.append(row_dict)

                sanitized_rows = sanitize_query_results(rows)
                result_shape = analyze_result_shape(
                    executed_sql,
                    column_metadata,
                    sanitized_rows,
                )
                logger.info("Query successful: %s rows in %sms", len(sanitized_rows), execution_time_ms)

                payload: Dict[str, Any] = {
                    'success': True,
                    'rows': sanitized_rows,
                    'columns': [column.model_dump(mode="json") for column in column_metadata],
                    'column_names': column_names,
                    'column_types': column_types,
                    'result_shape': result_shape.model_dump(mode="json"),
                    'row_count': len(sanitized_rows),
                    'execution_time_ms': execution_time_ms,
                    'executed_sql': executed_sql,
                }
                if fallback_applied:
                    payload['fallback_applied'] = True
                    payload['fallback_reason'] = fallback_reason
                return payload

            # Execute query using clickhouse-connect
            result = self.client.query(clean_sql)
            return _result_to_payload(result, executed_sql=clean_sql)

        except Exception as e:
            error_msg = str(e)

            # Resilience retry for string date columns with ambiguous formats.
            if clean_sql and _is_clickhouse_date_parse_error(error_msg):
                retry_sql = _rewrite_todate_for_ambiguous_strings(clean_sql)
                if retry_sql != clean_sql:
                    logger.warning(
                        "Date parse error detected; retrying with safer toDate transformation."
                    )
                    logger.warning("Retry SQL sent to ClickHouse: %s", retry_sql)
                    try:
                        retry_result = self.client.query(retry_sql)

                        logger.info(
                            "Query successful after date-safe retry: %s rows in %sms",
                            len(getattr(retry_result, "result_rows", []) or []),
                            int((time.time() - start_time) * 1000),
                        )
                        return _result_to_payload(
                            retry_result,
                            executed_sql=retry_sql,
                            fallback_applied=True,
                            fallback_reason='date_parse_retry_todate_us_best_effort',
                        )
                    except Exception as retry_exc:
                        retry_error_msg = str(retry_exc)
                        logger.error(
                            "ClickHouse query failed after date-safe retry: %s",
                            retry_error_msg,
                        )
                        error_msg = (
                            f"{error_msg} | retry_with_date_safe_todate_failed: "
                            f"{retry_error_msg}"
                        )

            logger.error("ClickHouse query error: %s", error_msg)

            # Special handling for port misconfiguration
            if 'Port 9000 is for clickhouse-client' in error_msg or 'Connection refused' in error_msg:
                return {
                    'success': False,
                    'error': (
                        'ClickHouse connection error. '
                        'Ensure ClickHouse is running and CLICKHOUSE_PORT=8123 is set in .env file.'
                    )
                }

            return {
                'success': False,
                'error': f"Query execution failed: {error_msg[:200]}"
            }
    def test_connection(self) -> bool:
        """
        Test ClickHouse connection.
        
        Returns:
            bool: True if connected
        """
        try:
            result = self.execute_query("SELECT 1 as test")
            return result['success']
        except Exception:
            return False
    
    def get_tables(self, database: Optional[str] = None) -> List[str]:
        """
        Get list of tables in database.
        
        Args:
            database: Database name (uses default if not provided)
        
        Returns:
            list: Table names
        """
        db = database or self.database
        sql = f"SHOW TABLES FROM {db}"
        
        result = self.execute_query(sql)
        
        if result['success']:
            return [row['name'] for row in result['rows']]
        return []
    
    def get_table_schema(self, table_name: str, database: Optional[str] = None) -> Dict:
        """
        Get schema for a table.
        
        Args:
            table_name: Table name
            database: Database name
        
        Returns:
            dict: Schema information
        """
        db = database or self.database
        sql = f"DESCRIBE TABLE {db}.{table_name}"
        
        result = self.execute_query(sql)
        
        if result['success']:
            return {
                'columns': result['rows'],
                'column_names': [row['name'] for row in result['rows']],
                'column_types': {row['name']: row['type'] for row in result['rows']}
            }
        
        return {}


# Singleton instance
_clickhouse_executor = None

def get_clickhouse_executor() -> ClickHouseExecutor:
    """Get or create ClickHouse executor singleton."""
    global _clickhouse_executor
    if _clickhouse_executor is None:
        _clickhouse_executor = ClickHouseExecutor()
    return _clickhouse_executor


