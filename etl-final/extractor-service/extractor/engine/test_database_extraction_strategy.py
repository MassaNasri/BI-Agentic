"""
Unit tests for DatabaseExtractionStrategy

Tests cover:
1. Basic extraction functionality
2. Pagination with LIMIT/OFFSET
3. SQL injection prevention (CRITICAL)
4. Multiple database types (MySQL, PostgreSQL)
5. Idempotency
6. Error handling
7. Schema validation
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from database_extraction_strategy import DatabaseExtractionStrategy
from extraction_strategy import ExtractionConfig, ExtractionError, ValidationError


class TestDatabaseExtractionStrategy(unittest.TestCase):
    """Test DatabaseExtractionStrategy implementation"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.strategy = DatabaseExtractionStrategy()
    
    def _create_mysql_connection(self, rows_data):
        """Create a mock MySQL connection with test data"""
        mock_connection = Mock()
        mock_connection.__class__.__module__ = 'pymysql.connections'
        
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = rows_data
        mock_cursor.description = [(col, None, None, None, None, None, None) 
                                   for col in rows_data[0].keys()] if rows_data else []
        
        mock_connection.cursor.return_value = mock_cursor
        
        return mock_connection, mock_cursor
    
    def _create_postgres_connection(self, rows_data):
        """Create a mock PostgreSQL connection with test data"""
        mock_connection = Mock()
        mock_connection.__class__.__module__ = 'psycopg2.extensions'
        
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = rows_data
        mock_cursor.description = [(col, None, None, None, None, None, None) 
                                   for col in rows_data[0].keys()] if rows_data else []
        
        mock_connection.cursor.return_value = mock_cursor
        
        return mock_connection, mock_cursor
    
    # ===== Basic Extraction Tests =====
    
    def test_extract_batch_mysql_basic(self):
        """Test basic extraction from MySQL database"""
        test_data = [
            {'id': 1, 'name': 'Alice', 'email': 'alice@example.com'},
            {'id': 2, 'name': 'Bob', 'email': 'bob@example.com'},
        ]
        
        mock_connection, mock_cursor = self._create_mysql_connection(test_data)
        
        config = ExtractionConfig(
            source_id="test_users",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users"
            },
            batch_size=10
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        # Verify batch properties
        self.assertEqual(len(batch.rows), 2)
        
        # Verify lineage fields are present
        for row in batch.rows:
            self.assertIn('_batch_id', row)
            self.assertIn('_source_id', row)
            self.assertIn('_extracted_at', row)
            self.assertEqual(row['_source_id'], 'test_users')
        
        # Verify original data is preserved
        self.assertEqual(batch.rows[0]['id'], 1)
        self.assertEqual(batch.rows[0]['name'], 'Alice')
        self.assertEqual(batch.rows[0]['email'], 'alice@example.com')
        self.assertEqual(batch.rows[1]['id'], 2)
        self.assertEqual(batch.rows[1]['name'], 'Bob')
        self.assertEqual(batch.rows[1]['email'], 'bob@example.com')
        
        self.assertEqual(batch.source_id, "test_users")
        self.assertEqual(batch.offset, 0)
        self.assertEqual(batch.total_rows, 2)
        self.assertFalse(batch.has_more)  # Less than limit, so no more rows
        
        # Verify query was executed
        mock_cursor.execute.assert_called_once()
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('SELECT * FROM', executed_query)
        self.assertIn('`users`', executed_query)  # MySQL uses backticks
    
    def test_extract_batch_postgres_basic(self):
        """Test basic extraction from PostgreSQL database"""
        test_data = [
            {'id': 1, 'name': 'Alice'},
            {'id': 2, 'name': 'Bob'},
        ]
        
        mock_connection, mock_cursor = self._create_postgres_connection(test_data)
        
        config = ExtractionConfig(
            source_id="test_users",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users"
            },
            batch_size=10
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        # Verify batch properties
        self.assertEqual(len(batch.rows), 2)
        
        # Verify lineage fields are present
        for row in batch.rows:
            self.assertIn('_batch_id', row)
            self.assertIn('_source_id', row)
            self.assertIn('_extracted_at', row)
            self.assertEqual(row['_source_id'], 'test_users')
        
        # Verify original data is preserved
        self.assertEqual(batch.rows[0]['id'], 1)
        self.assertEqual(batch.rows[0]['name'], 'Alice')
        self.assertEqual(batch.rows[1]['id'], 2)
        self.assertEqual(batch.rows[1]['name'], 'Bob')
        
        # Verify PostgreSQL uses double quotes
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('"users"', executed_query)
    
    # ===== Pagination Tests =====
    
    def test_pagination_with_limit_offset(self):
        """Test that LIMIT and OFFSET are correctly applied"""
        test_data = [{'id': i} for i in range(10, 20)]  # 10 rows
        
        mock_connection, mock_cursor = self._create_mysql_connection(test_data)
        
        config = ExtractionConfig(
            source_id="test_table",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "data"
            },
            batch_size=10
        )
        
        batch = self.strategy.extract_batch(config, offset=10, limit=10)
        
        # Verify query contains LIMIT and OFFSET
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('LIMIT 10', executed_query)
        self.assertIn('OFFSET 10', executed_query)
        
        # Verify batch metadata
        self.assertEqual(batch.offset, 10)
        self.assertEqual(batch.total_rows, 10)
        self.assertTrue(batch.has_more)  # Exactly limit rows, might have more
    
    def test_pagination_last_batch(self):
        """Test that has_more is False when fewer rows than limit are returned"""
        test_data = [{'id': i} for i in range(5)]  # Only 5 rows
        
        mock_connection, mock_cursor = self._create_mysql_connection(test_data)
        
        config = ExtractionConfig(
            source_id="test_table",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "data"
            },
            batch_size=10
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        # Verify has_more is False (fewer rows than limit)
        self.assertFalse(batch.has_more)
        self.assertEqual(batch.total_rows, 5)
    
    def test_pagination_empty_result(self):
        """Test extraction when no rows are returned"""
        mock_connection, mock_cursor = self._create_mysql_connection([])
        
        config = ExtractionConfig(
            source_id="test_table",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "empty_table"
            },
            batch_size=10
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        # Verify empty batch
        self.assertEqual(len(batch.rows), 0)
        self.assertFalse(batch.has_more)
        self.assertEqual(batch.total_rows, 0)
    
    # ===== SQL Injection Prevention Tests (CRITICAL) =====
    
    def test_sql_injection_prevention_mysql(self):
        """Test that SQL injection attempts are prevented in MySQL"""
        mock_connection, mock_cursor = self._create_mysql_connection([])
        
        # Attempt SQL injection with malicious table name
        malicious_table = "users; DROP TABLE users; --"
        
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": malicious_table
            },
            batch_size=10
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        # Verify the malicious SQL is escaped and treated as a table name
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('`users; DROP TABLE users; --`', executed_query)
        # Verify it's a single SELECT statement
        self.assertEqual(executed_query.count('SELECT'), 1)
        self.assertNotIn('DROP TABLE', executed_query.replace('`users; DROP TABLE users; --`', ''))
    
    def test_sql_injection_prevention_postgres(self):
        """Test that SQL injection attempts are prevented in PostgreSQL"""
        mock_connection, mock_cursor = self._create_postgres_connection([])
        
        # Attempt SQL injection with malicious table name
        malicious_table = "users; DROP TABLE users; --"
        
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": malicious_table
            },
            batch_size=10
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        # Verify the malicious SQL is escaped
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('"users; DROP TABLE users; --"', executed_query)
        self.assertEqual(executed_query.count('SELECT'), 1)
    
    def test_sql_injection_union_attack(self):
        """Test that UNION-based SQL injection is prevented"""
        mock_connection, mock_cursor = self._create_mysql_connection([])
        
        malicious_table = "users UNION SELECT password FROM admin"
        
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": malicious_table
            },
            batch_size=10
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        # Verify UNION is escaped
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('`users UNION SELECT password FROM admin`', executed_query)
    
    def test_sql_injection_with_backticks_mysql(self):
        """Test that backticks in table names are properly escaped for MySQL"""
        mock_connection, mock_cursor = self._create_mysql_connection([])
        
        table_with_backtick = "user`table"
        
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": table_with_backtick
            },
            batch_size=10
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        # Verify backticks are escaped (` becomes ``)
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('`user``table`', executed_query)
    
    def test_sql_injection_with_quotes_postgres(self):
        """Test that double quotes in table names are properly escaped for PostgreSQL"""
        mock_connection, mock_cursor = self._create_postgres_connection([])
        
        table_with_quote = 'user"table'
        
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": table_with_quote
            },
            batch_size=10
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        # Verify quotes are escaped (" becomes "")
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('"user""table"', executed_query)
    
    def test_sql_injection_unknown_database_validation(self):
        """Test that unknown database types validate table names"""
        mock_connection = Mock()
        mock_connection.__class__.__module__ = 'unknown.database'
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = []
        mock_connection.cursor.return_value = mock_cursor
        
        # Valid table name should work
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "valid_table_123"
            },
            batch_size=10
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        # Should succeed without quoting
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('valid_table_123', executed_query)
    
    def test_sql_injection_unknown_database_rejects_invalid(self):
        """Test that unknown database types reject invalid table names"""
        mock_connection = Mock()
        mock_connection.__class__.__module__ = 'unknown.database'
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        
        # Invalid table name with special characters
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users; DROP TABLE"
            },
            batch_size=10
        )
        
        # Should raise ValueError
        with self.assertRaises(ExtractionError) as context:
            self.strategy.extract_batch(config, offset=0, limit=10)
        
        self.assertIn('Invalid identifier', str(context.exception))
    
    # ===== ORDER BY Tests =====
    
    def test_order_by_clause(self):
        """Test that ORDER BY clause is properly added and quoted"""
        test_data = [{'id': 1}, {'id': 2}]
        mock_connection, mock_cursor = self._create_mysql_connection(test_data)
        
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users",
                "order_by": "created_at"
            },
            batch_size=10
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        # Verify ORDER BY is in query with proper quoting
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('ORDER BY `created_at`', executed_query)
    
    def test_order_by_sql_injection_prevention(self):
        """Test that ORDER BY column names are also protected from SQL injection"""
        test_data = [{'id': 1}]
        mock_connection, mock_cursor = self._create_mysql_connection(test_data)
        
        # Malicious ORDER BY
        malicious_order = "id; DROP TABLE users"
        
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users",
                "order_by": malicious_order
            },
            batch_size=10
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        # Verify ORDER BY is quoted
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('`id; DROP TABLE users`', executed_query)
    
    # ===== WHERE Clause Tests =====
    
    def test_where_clause(self):
        """Test that WHERE clause is properly added"""
        test_data = [{'id': 1, 'active': True}]
        mock_connection, mock_cursor = self._create_mysql_connection(test_data)
        
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users",
                "where_clause": "active = 1"
            },
            batch_size=10
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        # Verify WHERE clause is in query
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('WHERE active = 1', executed_query)

    def test_where_clause_rejects_stacked_query_tokens(self):
        test_data = [{'id': 1}]
        mock_connection, _ = self._create_mysql_connection(test_data)

        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users",
                "where_clause": "active = 1; DROP TABLE users"
            },
            batch_size=10
        )

        with self.assertRaises(ExtractionError):
            self.strategy.extract_batch(config, offset=0, limit=10)
    
    # ===== Idempotency Tests =====
    
    def test_idempotency_same_batch_id(self):
        """Test that same source_id and offset produce same batch_id"""
        test_data = [{'id': 1}]
        mock_connection, mock_cursor = self._create_mysql_connection(test_data)
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users"
            },
            batch_size=10
        )
        
        batch1 = self.strategy.extract_batch(config, offset=0, limit=10)
        
        # Reset mock
        mock_cursor.reset_mock()
        mock_cursor.fetchall.return_value = test_data
        
        batch2 = self.strategy.extract_batch(config, offset=0, limit=10)
        
        # Verify batch_ids are identical
        self.assertEqual(batch1.batch_id, batch2.batch_id)
    
    def test_idempotency_different_offsets(self):
        """Test that different offsets produce different batch_ids"""
        test_data = [{'id': 1}]
        mock_connection, mock_cursor = self._create_mysql_connection(test_data)
        
        config = ExtractionConfig(
            source_id="test_source",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users"
            },
            batch_size=10
        )
        
        batch1 = self.strategy.extract_batch(config, offset=0, limit=10)
        batch2 = self.strategy.extract_batch(config, offset=10, limit=10)
        
        # Verify batch_ids are different
        self.assertNotEqual(batch1.batch_id, batch2.batch_id)
    
    # ===== Configuration Validation Tests =====
    
    def test_validate_config_missing_connection(self):
        """Test that missing connection raises ValueError"""
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "table": "users"
            },
            batch_size=10
        )
        
        with self.assertRaises(ExtractionError) as context:
            self.strategy.extract_batch(config, offset=0, limit=10)
        
        self.assertIn('connection is required', str(context.exception))
    
    def test_validate_config_missing_table(self):
        """Test that missing table raises ValueError"""
        mock_connection = Mock()
        
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection
            },
            batch_size=10
        )
        
        with self.assertRaises(ExtractionError) as context:
            self.strategy.extract_batch(config, offset=0, limit=10)
        
        self.assertIn('table is required', str(context.exception))
    
    def test_validate_config_empty_table_name(self):
        """Test that empty table name raises ValueError"""
        mock_connection = Mock()
        
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": ""
            },
            batch_size=10
        )
        
        with self.assertRaises(ExtractionError) as context:
            self.strategy.extract_batch(config, offset=0, limit=10)
        
        self.assertIn('table must be a non-empty string', str(context.exception))
    
    def test_validate_config_whitespace_table_name(self):
        """Test that whitespace-only table name raises ValueError"""
        mock_connection = Mock()
        mock_connection.__class__.__module__ = 'unknown.database'
        
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "   "
            },
            batch_size=10
        )
        
        with self.assertRaises(ExtractionError) as context:
            self.strategy.extract_batch(config, offset=0, limit=10)
        
        self.assertIn('table must be a non-empty string', str(context.exception))
    
    # ===== Schema Validation Tests =====
    
    def test_schema_validation_success(self):
        """Test that schema validation passes with valid data"""
        test_data = [
            {'id': 1, 'name': 'Alice', 'email': 'alice@example.com'}
        ]
        mock_connection, mock_cursor = self._create_mysql_connection(test_data)
        
        schema_contract = {
            "fields": [
                {"name": "id", "required": True},
                {"name": "name", "required": True},
                {"name": "email", "required": True}
            ]
        }
        
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users"
            },
            batch_size=10,
            schema_contract=schema_contract
        )
        
        # Should not raise
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        self.assertEqual(len(batch.rows), 1)
    
    def test_schema_validation_missing_required_field(self):
        """Test that schema validation fails when required field is missing"""
        test_data = [
            {'id': 1, 'name': 'Alice'}  # Missing 'email'
        ]
        mock_connection, mock_cursor = self._create_mysql_connection(test_data)
        
        schema_contract = {
            "fields": [
                {"name": "id", "required": True},
                {"name": "name", "required": True},
                {"name": "email", "required": True}
            ]
        }
        
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users"
            },
            batch_size=10,
            schema_contract=schema_contract
        )
        
        with self.assertRaises(ValidationError) as context:
            self.strategy.extract_batch(config, offset=0, limit=10)
        
        self.assertIn('Missing required fields', str(context.exception))
        self.assertIn('email', str(context.exception))

    def test_schema_validation_fails_on_later_row_missing_required_field(self):
        """Regression: validate all rows in batch, not just first row."""
        test_data = [
            {'id': 1, 'name': 'Alice', 'email': 'alice@example.com'},
            {'id': 2, 'name': 'Bob', 'email': None},
        ]
        mock_connection, _ = self._create_mysql_connection(test_data)

        schema_contract = {
            "fields": [
                {"name": "id", "required": True},
                {"name": "name", "required": True},
                {"name": "email", "required": True}
            ]
        }

        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users"
            },
            batch_size=10,
            schema_contract=schema_contract
        )

        with self.assertRaises(ValidationError):
            self.strategy.extract_batch(config, offset=0, limit=10)
    
    # ===== Error Handling Tests =====
    
    def test_database_error_handling(self):
        """Test that database errors are properly wrapped in ExtractionError"""
        mock_connection = Mock()
        mock_connection.__class__.__module__ = 'pymysql.connections'
        mock_cursor = Mock()
        mock_cursor.execute.side_effect = Exception("Database connection failed")
        mock_connection.cursor.return_value = mock_cursor
        
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users"
            },
            batch_size=10
        )
        
        with self.assertRaises(ExtractionError) as context:
            self.strategy.extract_batch(config, offset=0, limit=10)
        
        self.assertIn('Failed to extract database data', str(context.exception))
    
    # ===== Metadata Tests =====
    
    def test_batch_metadata_contains_query(self):
        """Test that batch metadata includes the executed query for auditing"""
        test_data = [{'id': 1}]
        mock_connection, mock_cursor = self._create_mysql_connection(test_data)
        
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users"
            },
            batch_size=10
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        # Verify metadata contains query
        self.assertIn('query', batch.metadata)
        self.assertIn('SELECT * FROM', batch.metadata['query'])
        self.assertIn('LIMIT', batch.metadata['query'])
        self.assertIn('OFFSET', batch.metadata['query'])
    
    def test_batch_metadata_contains_database_type(self):
        """Test that batch metadata includes database type"""
        test_data = [{'id': 1}]
        mock_connection, mock_cursor = self._create_mysql_connection(test_data)
        
        config = ExtractionConfig(
            source_id="test",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users"
            },
            batch_size=10
        )
        
        batch = self.strategy.extract_batch(config, offset=0, limit=10)
        
        # Verify metadata contains database type
        self.assertIn('database_type', batch.metadata)
        self.assertEqual(batch.metadata['database_type'], 'mysql')

    # ===== No-PK Pagination Mode Tests =====

    def test_no_pk_fail_mode_raises(self):
        test_data = [{'id': 1}]
        mock_connection, _ = self._create_mysql_connection(test_data)
        config = ExtractionConfig(
            source_id="test_source",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users"
            },
            batch_size=10
        )

        with patch.dict("os.environ", {"DB_NO_PK_MODE": "fail"}, clear=False):
            with self.assertRaises(ExtractionError):
                self.strategy.extract_batch(config, offset=0, limit=10)

    def test_no_pk_warn_mode_best_effort_offset(self):
        test_data = [{'id': 1}, {'id': 2}]
        mock_connection, mock_cursor = self._create_mysql_connection(test_data)
        config = ExtractionConfig(
            source_id="test_source",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users"
            },
            batch_size=10
        )

        with patch.dict("os.environ", {"DB_NO_PK_MODE": "warn"}, clear=False):
            batch = self.strategy.extract_batch(config, offset=0, limit=10)

        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn("LIMIT 10 OFFSET 0", executed_query)
        self.assertNotIn("ORDER BY", executed_query)
        self.assertTrue(batch.metadata["nondeterministic_paging"])
        self.assertEqual(batch.metadata["pagination_mode"], "best_effort_offset")
        self.assertEqual(batch.metadata["no_pk_mode"], "warn")

    def test_no_pk_postgres_uses_ctid_fallback(self):
        test_data = [{'id': 1}, {'id': 2}]
        mock_connection, mock_cursor = self._create_postgres_connection(test_data)
        config = ExtractionConfig(
            source_id="test_source",
            source_type="database",
            connection_params={
                "connection": mock_connection,
                "table": "users"
            },
            batch_size=10
        )

        with patch.dict("os.environ", {"DB_NO_PK_MODE": "warn"}, clear=False):
            batch = self.strategy.extract_batch(config, offset=0, limit=10)

        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('ORDER BY "ctid"', executed_query)
        self.assertIn("LIMIT 10 OFFSET 0", executed_query)
        self.assertEqual(batch.metadata["pagination_mode"], "physical_order_ctid")
        self.assertEqual(batch.metadata["fallback_strategy"], "postgres_ctid")
        self.assertTrue(batch.metadata["nondeterministic_paging"])


if __name__ == '__main__':
    unittest.main()
