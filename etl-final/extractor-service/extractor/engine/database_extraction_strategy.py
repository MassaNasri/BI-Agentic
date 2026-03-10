"""
Database Extraction Strategy

This module implements the ExtractionStrategy interface for database extraction.
Uses LIMIT/OFFSET pagination to prevent memory overflow with large tables.

CRITICAL SECURITY: Uses parameterized queries and identifier quoting to prevent SQL injection.
This addresses the critical vulnerability identified in Section 9.1 of the requirements.

Design Principles:
- Stateless: No instance variables that change between calls
- Idempotent: Same input produces same output
- Memory-efficient: Uses pagination with LIMIT/OFFSET
- Secure: Prevents SQL injection via identifier quoting (NOT f-strings)
- Database-agnostic: Supports MySQL, PostgreSQL, and other databases

Requirements:
- FR-6: Idempotent Operations
- US-1: Idempotent ETL operations (AC 1.4: Pipeline state is externalized)
- NFR-1: Performance - Memory: O(batch_size) not O(total_rows)
- NFR-4: Security - No SQL injection vulnerabilities
- Section 9.1: CRITICAL - SQL Injection vulnerability must be fixed
"""

from typing import Dict, Any, Optional
from datetime import datetime, timezone
import re
import os
import logging

try:
    from .extraction_strategy import (
        ExtractionStrategy,
        Batch,
        ExtractionConfig,
        ExtractionError,
        ValidationError
    )
except ImportError:  # pragma: no cover - compatibility with legacy direct imports
    from extraction_strategy import (  # type: ignore
        ExtractionStrategy,
        Batch,
        ExtractionConfig,
        ExtractionError,
        ValidationError
    )


class DatabaseExtractionStrategy(ExtractionStrategy):
    """
    Extraction strategy for database tables using pagination.
    
    This strategy extracts data from database tables in batches using LIMIT/OFFSET
    to prevent memory overflow issues with large tables. It supports multiple
    database types (MySQL, PostgreSQL, etc.) and uses proper identifier quoting
    to prevent SQL injection attacks.
    
    CRITICAL SECURITY FEATURE:
    - Uses identifier quoting (backticks for MySQL, double quotes for PostgreSQL)
    - Escapes special characters in table names
    - Validates table names for unknown database types
    - NEVER uses f-strings for SQL construction without quoting
    
    Key Features:
    - Paginated extraction: Uses LIMIT/OFFSET for memory efficiency
    - SQL injection prevention: Proper identifier quoting
    - Connection pooling support: Reuses connections efficiently
    - Database-agnostic: Detects database type and uses appropriate SQL dialect
    - Idempotent: Same offset always returns same data
    - Stateless: No mutable instance state
    
    Connection Parameters:
        connection: Database connection object (required)
        table: Table name to extract from (required)
        where_clause: Optional WHERE clause for filtering (default: None)
        order_by: Optional ORDER BY clause for consistent ordering (default: primary key)
        
    Example:
        import pymysql
        
        connection = pymysql.connect(
            host='localhost',
            user='user',
            password='pass',
            database='mydb',
            cursorclass=pymysql.cursors.DictCursor
        )
        
        config = ExtractionConfig(
            source_id="customers_db",
            source_type="database",
            connection_params={
                "connection": connection,
                "table": "customers",
                "order_by": "customer_id"
            },
            batch_size=1000
        )
        
        strategy = DatabaseExtractionStrategy()
        batch = strategy.extract_batch(config, offset=0, limit=1000)
    """
    
    def extract_batch(
        self,
        config: ExtractionConfig,
        offset: int,
        limit: int
    ) -> Batch:
        """
        Extract a batch of rows from a database table.
        
        Uses LIMIT/OFFSET pagination to efficiently extract data starting from
        the given offset. The method is idempotent - calling with the same
        config and offset will always return the same data (assuming the table
        doesn't change).
        
        SECURITY: Uses identifier quoting to prevent SQL injection. Table names
        are quoted using database-specific quoting (backticks for MySQL, double
        quotes for PostgreSQL) and special characters are escaped.
        
        Args:
            config: Configuration containing connection and table parameters
            offset: Starting row position (0-indexed)
            limit: Maximum number of rows to extract
            
        Returns:
            Batch object containing extracted rows and metadata
            
        Raises:
            ExtractionError: If database query fails or connection issues occur
            ValidationError: If data fails schema validation (if schema_contract provided)
        """
        # Validate configuration
        try:
            self.validate_config(config)
            self._validate_database_config(config)
        except ValueError as e:
            raise ExtractionError(str(e))
        
        # Extract connection parameters
        connection = config.connection_params["connection"]
        table = config.connection_params["table"]
        where_clause = config.connection_params.get("where_clause")
        order_by = config.connection_params.get("order_by")
        pk_column = config.connection_params.get("pk_column")
        last_pk = config.connection_params.get("last_pk")
        
        # Estimate total rows for progress tracking (if at offset 0)
        estimated_total_rows = None
        if offset == 0 and config.progress_tracker:
            estimated_total_rows = self._estimate_total_rows(connection, table, where_clause)
        
        try:
            # Get database type and quote table name appropriately
            quoted_table = self._quote_identifier(connection, table)
            db_type = self._detect_database_type(connection)
            pagination_mode = "offset"
            nondeterministic_paging = False
            fallback_strategy = None
            params = []

            no_pk_mode = self._get_no_pk_mode()
            if not order_by and not pk_column:
                if db_type == "postgres":
                    order_by = "ctid"
                    pagination_mode = "physical_order_ctid"
                    nondeterministic_paging = True
                    fallback_strategy = "postgres_ctid"
                    logging.getLogger(__name__).warning(
                        "No PK/order_by for table '%s'; using PostgreSQL ctid fallback (nondeterministic risk)",
                        table,
                    )
                elif no_pk_mode == "fail":
                    raise ExtractionError(
                        f"Deterministic ordering required for table '{table}': "
                        "provide order_by or pk_column, or set DB_NO_PK_MODE=warn|best_effort"
                    )
                else:
                    pagination_mode = "best_effort_offset"
                    nondeterministic_paging = True
                    fallback_strategy = "unordered_limit_offset"
                    logging.getLogger(__name__).warning(
                        "No PK/order_by for table '%s'; using unordered LIMIT/OFFSET fallback (nondeterministic)",
                        table,
                    )

            query = f"SELECT * FROM {quoted_table}"
            where_clauses = []

            if where_clause:
                where_clauses.append(where_clause)

            if pk_column and (order_by is None or order_by == pk_column):
                pagination_mode = "keyset"
                quoted_pk = self._quote_identifier(connection, pk_column)
                if last_pk is not None:
                    where_clauses.append(f"{quoted_pk} > %s")
                    params.append(last_pk)
                if where_clauses:
                    query += f" WHERE {' AND '.join(where_clauses)}"
                query += f" ORDER BY {quoted_pk} ASC LIMIT {limit}"
            else:
                if where_clauses:
                    query += f" WHERE {' AND '.join(where_clauses)}"
                if order_by:
                    quoted_order_by = self._quote_identifier(connection, order_by)
                    query += f" ORDER BY {quoted_order_by} LIMIT {limit} OFFSET {offset}"
                else:
                    query += f" LIMIT {limit} OFFSET {offset}"

            # Execute query
            cursor = connection.cursor()
            if params:
                cursor.execute(query, tuple(params))
            else:
                cursor.execute(query)
            rows = cursor.fetchall()
            
            # Convert rows to list of dictionaries if needed
            if rows and not isinstance(rows[0], dict):
                # If cursor doesn't return dicts, convert tuples to dicts
                columns = [desc[0] for desc in cursor.description]
                rows = [dict(zip(columns, row)) for row in rows]
            
            # Determine if there are more rows
            has_more = len(rows) == limit
            next_last_pk = None
            if pagination_mode == "keyset" and rows:
                next_last_pk = rows[-1].get(pk_column)
            
            # Generate batch metadata
            batch_id = self.generate_batch_id(config.source_id, offset)
            extraction_timestamp = datetime.now(timezone.utc)
            
            # Enrich rows with lineage metadata (_batch_id, _source_id, _extracted_at)
            # This ensures every row can be traced back to its source and extraction batch
            enriched_rows = self.enrich_rows_with_lineage(
                rows=rows,
                batch_id=batch_id,
                source_id=config.source_id,
                extracted_at=extraction_timestamp
            )
            
            metadata = {
                "table": table,
                "database_type": db_type,
                "extraction_timestamp": extraction_timestamp.isoformat(),
                "rows_extracted": len(enriched_rows),
                "query": query,  # Include query for debugging/auditing
                "offset": offset,
                "limit": limit,
                "order_by": order_by or pk_column,
                "pagination_mode": pagination_mode,
                "pk_column": pk_column,
                "last_pk": last_pk,
                "next_last_pk": next_last_pk,
                "nondeterministic_paging": nondeterministic_paging,
                "no_pk_mode": no_pk_mode,
                "fallback_strategy": fallback_strategy,
            }
            
            # Validate against schema contract if provided
            # Note: Validate original rows before enrichment to check source schema
            if config.schema_contract and rows:
                self._validate_schema(rows, config.schema_contract)
            
            # Update progress tracking
            if config.progress_tracker:
                # Calculate cumulative rows extracted (offset + current batch)
                cumulative_rows = offset + len(enriched_rows)
                # Batches processed is based on offset (how many batches came before) + 1 (current)
                batches_processed = (offset // limit) + 1
                
                self._update_progress(
                    config=config,
                    rows_extracted=cumulative_rows,
                    batches_processed=batches_processed,
                    current_offset=offset + len(enriched_rows),
                    estimated_total_rows=estimated_total_rows
                )
            
            return Batch(
                rows=enriched_rows,
                batch_id=batch_id,
                source_id=config.source_id,
                offset=offset,
                total_rows=len(enriched_rows),
                has_more=has_more,
                metadata=metadata
            )
            
        except ValidationError:
            # Re-raise ValidationError without wrapping
            raise
        except Exception as e:
            raise ExtractionError(f"Failed to extract database data: {str(e)}")

    def _get_no_pk_mode(self) -> str:
        raw = os.getenv("DB_NO_PK_MODE", "warn").strip().lower()
        if raw not in {"fail", "warn", "best_effort"}:
            return "warn"
        return raw
    
    def _validate_database_config(self, config: ExtractionConfig) -> None:
        """
        Validate database-specific configuration parameters.
        
        Args:
            config: Configuration to validate
            
        Raises:
            ValueError: If database-specific parameters are invalid
        """
        # Check connection_params is not empty dict
        if not config.connection_params:
            raise ValueError("connection_params cannot be empty for database extraction")
        
        if "connection" not in config.connection_params:
            raise ValueError("connection is required in connection_params for database extraction")
        
        if "table" not in config.connection_params:
            raise ValueError("table is required in connection_params for database extraction")
        
        connection = config.connection_params["connection"]
        if connection is None:
            raise ValueError("connection cannot be None")
        
        table = config.connection_params["table"]
        if not isinstance(table, str) or not table.strip():
            raise ValueError("table must be a non-empty string")
        
        # Validate optional parameters if provided
        if "where_clause" in config.connection_params:
            where_clause = config.connection_params["where_clause"]
            if where_clause is not None and not isinstance(where_clause, str):
                raise ValueError("where_clause must be a string or None")
            if isinstance(where_clause, str):
                self._validate_where_clause(where_clause)
        
        if "order_by" in config.connection_params:
            order_by = config.connection_params["order_by"]
            if order_by is not None and not isinstance(order_by, str):
                raise ValueError("order_by must be a string or None")

        if "pk_column" in config.connection_params:
            pk_column = config.connection_params["pk_column"]
            if pk_column is not None and not isinstance(pk_column, str):
                raise ValueError("pk_column must be a string or None")
    
    def _detect_database_type(self, connection) -> str:
        """
        Detect the database type from the connection object.
        
        Args:
            connection: Database connection object
            
        Returns:
            Database type string ('mysql', 'postgres', 'unknown')
        """
        connection_type = type(connection).__module__
        
        # Try to get cursor type as well for more reliable detection
        try:
            cursor = connection.cursor()
            cursor_type = type(cursor).__module__
        except:
            cursor_type = ""
        
        # Check for MySQL
        if 'pymysql' in connection_type or 'pymysql' in cursor_type or 'MySQLdb' in connection_type:
            return 'mysql'
        
        # Check for PostgreSQL
        if 'psycopg' in connection_type or 'psycopg' in cursor_type:
            return 'postgres'
        
        return 'unknown'

    def _validate_where_clause(self, where_clause: str) -> None:
        """
        Lightweight guardrail against stacked queries/comment injection.
        """
        candidate = where_clause.strip()
        lowered = candidate.lower()
        if ";" in candidate or "--" in lowered or "/*" in lowered or "*/" in lowered:
            raise ValueError("where_clause contains disallowed SQL control tokens")
    
    def _quote_identifier(self, connection, identifier: str) -> str:
        """
        Quote a database identifier (table name, column name) to prevent SQL injection.
        
        CRITICAL SECURITY FUNCTION:
        This function implements the SQL injection prevention mechanism by:
        1. Detecting the database type
        2. Using database-specific identifier quoting
        3. Escaping special characters within the identifier
        
        For MySQL: Uses backticks (`) and escapes backticks as (``)
        For PostgreSQL: Uses double quotes (") and escapes quotes as ("")
        For unknown databases: Validates identifier contains only safe characters
        
        Args:
            connection: Database connection object
            identifier: Table name or column name to quote
            
        Returns:
            Properly quoted identifier safe for SQL query construction
            
        Raises:
            ValueError: If identifier is invalid (empty, whitespace-only, or contains
                       unsafe characters for unknown database types)
        """
        # Validate identifier is not empty or whitespace-only
        if not identifier or not identifier.strip():
            raise ValueError(f"Invalid identifier: identifier cannot be empty or whitespace-only")
        
        db_type = self._detect_database_type(connection)
        
        if db_type == 'mysql':
            # MySQL uses backticks for identifier quoting
            # Escape any backticks in the identifier by doubling them
            escaped = identifier.replace('`', '``')
            return f"`{escaped}`"
        
        elif db_type == 'postgres':
            # PostgreSQL uses double quotes for identifier quoting
            # Escape any double quotes in the identifier by doubling them
            escaped = identifier.replace('"', '""')
            return f'"{escaped}"'
        
        else:
            # For unknown database types, validate identifier contains only safe characters
            # This is a fallback security measure
            if not re.match(r'^[a-zA-Z0-9_]+$', identifier):
                raise ValueError(
                    f"Invalid identifier: '{identifier}' contains unsafe characters. "
                    f"For unknown database types, identifiers must contain only "
                    f"alphanumeric characters and underscores."
                )
            return identifier
    
    def _validate_schema(self, rows: list[Dict[str, Any]], schema_contract: Dict[str, Any]) -> None:
        """
        Validate a sample row against the schema contract.
        
        This is a basic validation that checks if required fields exist.
        More sophisticated validation can be added based on schema_contract structure.
        
        Args:
            rows: Rows from the extracted batch
            schema_contract: Schema contract to validate against
            
        Raises:
            ValidationError: If validation fails
        """
        if "fields" in schema_contract:
            required_fields = [
                field["name"] 
                for field in schema_contract["fields"] 
                if field.get("required", False)
            ]
            
            for idx, row in enumerate(rows):
                missing_fields = []
                for field in required_fields:
                    value = row.get(field) if field in row else None
                    if field not in row or value is None or value == "" or value != value:
                        missing_fields.append(field)
                if missing_fields:
                    raise ValidationError(
                        f"Missing required fields in database row {idx}: {', '.join(missing_fields)}"
                    )

    def _estimate_total_rows(
        self,
        connection,
        table: str,
        where_clause: Optional[str] = None
    ) -> Optional[int]:
        """
        Estimate total number of rows in database table for progress tracking.
        
        Uses COUNT(*) query to get accurate row count.
        
        Args:
            connection: Database connection object
            table: Table name
            where_clause: Optional WHERE clause for filtering
            
        Returns:
            Total row count or None if estimation fails
        """
        try:
            # Quote table name for safety
            quoted_table = self._quote_identifier(connection, table)
            
            # Build COUNT query
            query = f"SELECT COUNT(*) as total FROM {quoted_table}"
            
            if where_clause:
                query += f" WHERE {where_clause}"
            
            # Execute query
            cursor = connection.cursor()
            cursor.execute(query)
            result = cursor.fetchone()
            
            # Extract count from result
            if isinstance(result, dict):
                return result.get('total', 0)
            elif isinstance(result, (tuple, list)):
                return result[0]
            else:
                return None
        except Exception:
            # If estimation fails, return None
            return None

    def detect_primary_key(self, connection, table: str) -> Optional[str]:
        """
        Detect a table primary key column for deterministic keyset pagination.
        """
        db_type = self._detect_database_type(connection)
        cursor = connection.cursor()
        try:
            if db_type == "mysql":
                cursor.execute(
                    """
                    SELECT COLUMN_NAME
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = %s
                      AND COLUMN_KEY = 'PRI'
                    ORDER BY ORDINAL_POSITION
                    LIMIT 1
                    """,
                    (table,),
                )
            elif db_type == "postgres":
                cursor.execute(
                    """
                    SELECT a.attname
                    FROM pg_index i
                    JOIN pg_attribute a
                      ON a.attrelid = i.indrelid
                     AND a.attnum = ANY(i.indkey)
                    WHERE i.indrelid = to_regclass(%s)
                      AND i.indisprimary
                    ORDER BY a.attnum
                    LIMIT 1
                    """,
                    (table,),
                )
            else:
                return None

            result = cursor.fetchone()
            if result is None:
                return None
            if isinstance(result, dict):
                return result.get("COLUMN_NAME") or result.get("attname")
            if isinstance(result, (tuple, list)) and result:
                return result[0]
            return None
        except Exception:
            return None
