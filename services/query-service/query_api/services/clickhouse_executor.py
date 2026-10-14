"""
ClickHouse Executor

Executes validated SQL queries on ClickHouse.
Returns results for visualization.
"""

import os
import logging
import math
import re
import hashlib
import json
import time
import threading
from typing import Dict, List, Optional, Any

try:
    import clickhouse_connect
except ModuleNotFoundError:  # pragma: no cover - depends on runtime environment
    clickhouse_connect = None

from bi_platform_shared.contracts.query import build_column_metadata
from query_api.resource_policy import QueryResourcePolicy
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

        logger.info("Initializing authoritative ClickHouse query client")

        try:
            client = clickhouse_connect.get_client(
                host=host,
                port=port,
                username=username,
                password=password,
                database=database
            )
            version_result = client.query(
                "SELECT version()",
                settings=QueryResourcePolicy.from_environment().clickhouse_settings(
                    result_row_limit=1
                ),
            )
            version = (
                version_result.result_rows[0][0]
                if version_result.result_rows and version_result.result_rows[0]
                else "unknown"
            )
            logger.info("ClickHouse query client verified version=%s", version)
        except Exception as exc:
            error_msg = str(exc)
            logger.error(
                "ClickHouse query client initialization failed error_type=%s",
                type(exc).__name__,
            )
            if 'AUTHENTICATION_FAILED' in error_msg or 'Authentication failed' in error_msg:
                raise RuntimeError(
                    "ClickHouse authentication failed. Verify the query-service credential configuration."
                ) from exc
            raise RuntimeError(
                "ClickHouse query client initialization failed."
            ) from exc

        self.host = host
        self.port = port
        self.user = username
        self.password = password
        self.database = database
        self.client = client

    def execute_query(
        self,
        sql: str,
        workspace_database: Optional[str] = None,
        *,
        policy: QueryResourcePolicy | None = None,
        page: object = None,
        page_size: object = None,
        query_id: str = "",
    ) -> Dict:
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
        policy = policy or QueryResourcePolicy.from_environment()
        try:
            start_time = time.time()

            if not str(sql or "").lstrip().upper().startswith(("SELECT", "WITH")):
                return {
                    "success": False,
                    "error": "Only read-only SELECT/WITH queries may be executed.",
                    "error_code": "VALIDATION_REJECTED",
                }

            normalized_sql = sql
            normalize_db = workspace_database or self.database
            # Only normalize SELECT queries; keep admin statements unchanged.
            if sql and sql.strip().upper().startswith("SELECT"):
                normalized_sql = normalize_sql_table_references(sql, normalize_db)

            # Sanitize SQL for HTTP execution (removes FORMAT Native, semicolons)
            clean_sql = sanitize_sql_for_http(normalized_sql)
            normalized_page, effective_page_size, offset = policy.page_options(
                page=page,
                page_size=page_size,
            )
            fetch_limit = effective_page_size + 1
            paged_sql = (
                "SELECT * FROM ("
                f"{clean_sql}"
                ") AS _biavora_page "
                f"LIMIT {fetch_limit} OFFSET {offset}"
            )
            settings_applied = policy.clickhouse_settings(result_row_limit=fetch_limit)
            query_settings = dict(settings_applied)
            if query_id:
                # clickhouse-connect 0.15 treats query_id as a per-query HTTP
                # transport parameter when supplied through settings. Its
                # transport_settings argument is a raw HTTP-header mapping.
                query_settings["query_id"] = query_id
            sql_hash = hashlib.sha256(clean_sql.encode("utf-8")).hexdigest()

            def _result_to_payload(
                raw_result: Any,
                *,
                executed_sql: str,
                fallback_applied: bool = False,
                fallback_reason: str = "",
            ) -> Dict:
                execution_time_ms = int((time.time() - start_time) * 1000)

                rows: List[Dict[str, Any]] = []
                column_names = [str(name) for name in (getattr(raw_result, "column_names", []) or [])]
                column_types = [
                    _column_type_to_string(column_type)
                    for column_type in (getattr(raw_result, "column_types", []) or [])
                ]
                column_metadata = build_column_metadata(column_names, column_types)

                raw_rows = list(getattr(raw_result, "result_rows", []) or [])
                truncated = len(raw_rows) > effective_page_size
                for row in raw_rows[:effective_page_size]:
                    row_dict: Dict[str, Any] = {}
                    for i, col_name in enumerate(column_names):
                        row_dict[col_name] = row[i]
                    rows.append(row_dict)

                sanitized_rows = sanitize_query_results(rows)
                output_bytes = len(
                    json.dumps(
                        sanitized_rows,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8")
                )
                if output_bytes > policy.max_result_bytes:
                    return {
                        "success": False,
                        "error": "Query result exceeded the authorized response size.",
                        "error_code": "QUERY_LIMIT_EXCEEDED",
                        "execution_time_ms": execution_time_ms,
                        "output_bytes": output_bytes,
                        "settings_applied": settings_applied,
                        "query_id": query_id,
                        "sql_hash": sql_hash,
                    }
                result_shape = analyze_result_shape(
                    executed_sql,
                    column_metadata,
                    sanitized_rows,
                )
                summary = dict(getattr(raw_result, "summary", {}) or {})
                scanned_rows = summary.get("read_rows")
                read_bytes = summary.get("read_bytes")
                next_page = (
                    normalized_page + 1
                    if truncated and offset + effective_page_size < policy.max_rows
                    else None
                )
                logger.info(
                    "clickhouse_query_completed query_id=%s sql_hash=%s duration_ms=%s rows=%s output_bytes=%s",
                    query_id,
                    sql_hash,
                    execution_time_ms,
                    len(sanitized_rows),
                    output_bytes,
                )

                payload: Dict[str, Any] = {
                    'success': True,
                    'rows': sanitized_rows,
                    'columns': [column.model_dump(mode="json") for column in column_metadata],
                    'column_names': column_names,
                    'column_types': column_types,
                    'result_shape': result_shape.model_dump(mode="json"),
                    'row_count': len(sanitized_rows),
                    'execution_time_ms': execution_time_ms,
                    'scanned_rows': int(scanned_rows) if scanned_rows is not None else None,
                    'bytes_read': int(read_bytes) if read_bytes is not None else None,
                    'output_bytes': output_bytes,
                    'settings_applied': settings_applied,
                    'query_id': query_id or str(summary.get("query_id") or ""),
                    'sql_hash': sql_hash,
                    'pagination': {
                        'page': normalized_page,
                        'page_size': effective_page_size,
                        'returned_count': len(sanitized_rows),
                        'truncated': truncated,
                        'next_page': next_page,
                        'limit_reached': bool(truncated and next_page is None),
                        'max_rows': policy.max_rows,
                    },
                }
                if fallback_applied:
                    payload['fallback_applied'] = True
                    payload['fallback_reason'] = fallback_reason
                return payload

            # Execute query using clickhouse-connect
            result = self.client.query(
                paged_sql,
                settings=query_settings,
            )
            return _result_to_payload(result, executed_sql=paged_sql)

        except Exception as e:
            error_msg = str(e)

            # Resilience retry for string date columns with ambiguous formats.
            if clean_sql and _is_clickhouse_date_parse_error(error_msg):
                retry_sql = _rewrite_todate_for_ambiguous_strings(clean_sql)
                if retry_sql != clean_sql:
                    logger.warning(
                        "Date parse error detected; retrying with safer toDate transformation."
                    )
                    try:
                        retry_paged_sql = (
                            "SELECT * FROM ("
                            f"{retry_sql}"
                            ") AS _biavora_page "
                            f"LIMIT {fetch_limit} OFFSET {offset}"
                        )
                        retry_result = self.client.query(
                            retry_paged_sql,
                            settings=query_settings,
                        )

                        logger.info(
                            "Query successful after date-safe retry: %s rows in %sms",
                            len(getattr(retry_result, "result_rows", []) or []),
                            int((time.time() - start_time) * 1000),
                        )
                        return _result_to_payload(
                            retry_result,
                            executed_sql=retry_paged_sql,
                            fallback_applied=True,
                            fallback_reason='date_parse_retry_todate_us_best_effort',
                        )
                    except Exception as retry_exc:
                        retry_error_msg = str(retry_exc)
                        error_msg = retry_error_msg

            lowered_error = error_msg.lower()
            if any(token in lowered_error for token in ("timeout", "max_execution_time", "time limit")):
                error_code = "QUERY_TIMEOUT"
                safe_error = "Query execution exceeded the authorized timeout."
            elif any(token in lowered_error for token in ("cancelled", "canceled", "query was cancelled", "query was canceled")):
                error_code = "QUERY_CANCELLED"
                safe_error = "Query execution was cancelled."
            elif any(
                token in lowered_error
                for token in (
                    "max_result_rows",
                    "max_result_bytes",
                    "max_bytes_to_read",
                    "max_memory_usage",
                    "memory limit",
                    "too many rows",
                    "too_many_rows_or_bytes",
                    "too_many_bytes",
                    "limit for result exceeded",
                    "limit for bytes to read exceeded",
                    "limit for rows or bytes to read exceeded",
                    "limit exceeded",
                )
            ):
                error_code = "QUERY_LIMIT_EXCEEDED"
                safe_error = "Query execution exceeded an authorized resource limit."
            elif any(
                token in lowered_error
                for token in ("connection refused", "connection reset", "network", "unavailable", "timed out")
            ):
                error_code = "CLICKHOUSE_UNAVAILABLE"
                safe_error = "The analytical data service is temporarily unavailable."
            else:
                error_code = "INTERNAL_ERROR"
                safe_error = "Query execution failed."
            logger.warning(
                "clickhouse_query_failed query_id=%s error_code=%s error_type=%s",
                query_id,
                error_code,
                type(e).__name__,
            )
            return {
                'success': False,
                'error': safe_error,
                'error_code': error_code,
                'aborted_due_to_timeout': error_code == "QUERY_TIMEOUT",
                'settings_applied': settings_applied if 'settings_applied' in locals() else {},
                'query_id': query_id,
                'sql_hash': hashlib.sha256(clean_sql.encode("utf-8")).hexdigest() if clean_sql else None,
            }

    def cancel_query(self, query_id: str) -> Dict:
        query_id = str(query_id or "").strip()
        if not re.fullmatch(r"biavora-w[1-9][0-9]*-[a-f0-9]{32}", query_id):
            return {
                "success": False,
                "error": "Invalid cancellation request.",
                "error_code": "VALIDATION_REJECTED",
            }
        try:
            active_result = self.client.query(
                "SELECT count() FROM system.processes "
                "WHERE query_id = {query_id:String} AND user = currentUser()",
                parameters={"query_id": query_id},
            )
            active_count = int(active_result.result_rows[0][0])
            if active_count == 0:
                return {"success": True, "cancelled": False, "query_id": query_id}
            self.client.command(
                "KILL QUERY WHERE query_id = %(query_id)s AND user = currentUser() SYNC",
                parameters={"query_id": query_id},
            )
            logger.info("clickhouse_query_cancel_requested query_id=%s", query_id)
            return {"success": True, "cancelled": True, "query_id": query_id}
        except Exception as exc:
            logger.warning(
                "clickhouse_query_cancel_failed query_id=%s error_type=%s",
                query_id,
                type(exc).__name__,
            )
            return {
                "success": False,
                "error": "Query cancellation is temporarily unavailable.",
                "error_code": "CLICKHOUSE_UNAVAILABLE",
            }
    def test_connection(self) -> bool:
        """
        Test ClickHouse connection.
        
        Returns:
            bool: True if connected
        """
        try:
            policy = QueryResourcePolicy.from_environment()
            result = self.client.query(
                "SELECT 1 AS test",
                settings=policy.clickhouse_settings(result_row_limit=1),
            )
            return bool(getattr(result, "result_rows", None))
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


# clickhouse-connect sessions reject concurrent queries. Django may serve two
# requests on different threads, especially the query and its cancellation, so
# each request thread needs its own session.
_clickhouse_executor_local = threading.local()

def get_clickhouse_executor() -> ClickHouseExecutor:
    """Get or create the ClickHouse executor for the current request thread."""
    executor = getattr(_clickhouse_executor_local, "executor", None)
    if executor is None:
        executor = ClickHouseExecutor()
        _clickhouse_executor_local.executor = executor
    return executor


