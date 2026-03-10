"""
Unit tests for SQL injection prevention in extractor service
Tests that table name quoting prevents SQL injection attacks
"""
import unittest
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from .row_extractor import RowExtractor


class TestSQLInjectionPrevention(unittest.TestCase):
    """Test SQL injection prevention in row extractor"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.extractor = RowExtractor()
    
    def _create_mysql_mock(self):
        """Create a mock MySQL connection"""
        mock_connection = Mock()
        # Set __module__ directly as a string attribute
        mock_connection.__class__.__module__ = 'pymysql.connections'
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = []
        mock_connection.cursor.return_value = mock_cursor
        return mock_connection, mock_cursor
    
    def _create_postgres_mock(self):
        """Create a mock PostgreSQL connection"""
        mock_connection = Mock()
        # Set __module__ directly as a string attribute
        mock_connection.__class__.__module__ = 'psycopg2.extensions'
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = []
        mock_connection.cursor.return_value = mock_cursor
        return mock_connection, mock_cursor
    
    def test_mysql_table_name_quoting(self):
        """Test that MySQL table names are properly quoted with backticks"""
        mock_connection, mock_cursor = self._create_mysql_mock()
        mock_cursor.fetchall.return_value = [{'id': 1, 'name': 'test'}]
        
        # Test normal table name
        tables = ['users']
        list(self.extractor.extract_rows(mock_connection, tables))
        
        # Verify the query uses backticks
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('`users`', executed_query)
        self.assertEqual(executed_query, 'SELECT * FROM `users`')
    
    def test_mysql_table_name_with_backtick_escaping(self):
        """Test that backticks in table names are properly escaped for MySQL"""
        mock_connection, mock_cursor = self._create_mysql_mock()
        
        # Test table name with backtick (should be escaped)
        tables = ['user`table']
        list(self.extractor.extract_rows(mock_connection, tables))
        
        # Verify backticks are escaped (` becomes ``)
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('`user``table`', executed_query)
    
    def test_postgres_table_name_quoting(self):
        """Test that PostgreSQL table names are properly quoted with double quotes"""
        mock_connection, mock_cursor = self._create_postgres_mock()
        mock_cursor.fetchall.return_value = [{'id': 1, 'name': 'test'}]
        
        # Test normal table name
        tables = ['users']
        list(self.extractor.extract_rows(mock_connection, tables))
        
        # Verify the query uses double quotes
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('"users"', executed_query)
        self.assertEqual(executed_query, 'SELECT * FROM "users"')
    
    def test_postgres_table_name_with_quote_escaping(self):
        """Test that double quotes in table names are properly escaped for PostgreSQL"""
        mock_connection, mock_cursor = self._create_postgres_mock()
        
        # Test table name with double quote (should be escaped)
        tables = ['user"table']
        list(self.extractor.extract_rows(mock_connection, tables))
        
        # Verify double quotes are escaped (" becomes "")
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('"user""table"', executed_query)
    
    def test_sql_injection_attempt_mysql(self):
        """Test that SQL injection attempts are prevented in MySQL"""
        mock_connection, mock_cursor = self._create_mysql_mock()
        
        # Attempt SQL injection with malicious table name
        malicious_table = "users; DROP TABLE users; --"
        tables = [malicious_table]
        list(self.extractor.extract_rows(mock_connection, tables))
        
        # Verify the malicious SQL is escaped and treated as a table name
        executed_query = mock_cursor.execute.call_args[0][0]
        # The semicolons and dashes should be inside the backticks, making them harmless
        self.assertIn('`users; DROP TABLE users; --`', executed_query)
        # Verify it's a single SELECT statement, not multiple statements
        self.assertEqual(executed_query.count('SELECT'), 1)
    
    def test_sql_injection_attempt_postgres(self):
        """Test that SQL injection attempts are prevented in PostgreSQL"""
        mock_connection, mock_cursor = self._create_postgres_mock()
        
        # Attempt SQL injection with malicious table name
        malicious_table = "users; DROP TABLE users; --"
        tables = [malicious_table]
        list(self.extractor.extract_rows(mock_connection, tables))
        
        # Verify the malicious SQL is escaped and treated as a table name
        executed_query = mock_cursor.execute.call_args[0][0]
        # The semicolons and dashes should be inside the double quotes, making them harmless
        self.assertIn('"users; DROP TABLE users; --"', executed_query)
        # Verify it's a single SELECT statement, not multiple statements
        self.assertEqual(executed_query.count('SELECT'), 1)
    
    def test_fallback_validation_for_unknown_db(self):
        """Test that unknown database types use validation fallback"""
        mock_connection = Mock()
        mock_connection.__class__.__module__ = 'unknown.database'
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = []
        mock_connection.cursor.return_value = mock_cursor
        
        # Valid table name should work
        tables = ['valid_table_123']
        list(self.extractor.extract_rows(mock_connection, tables))
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertEqual(executed_query, 'SELECT * FROM valid_table_123')
    
    def test_fallback_validation_rejects_invalid_names(self):
        """Test that fallback validation rejects invalid table names"""
        mock_connection = Mock()
        mock_connection.__class__.__module__ = 'unknown.database'
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        
        # Invalid table name with special characters should raise error
        tables = ['users; DROP TABLE']
        
        with self.assertRaises(ValueError) as context:
            list(self.extractor.extract_rows(mock_connection, tables))
        
        self.assertIn('Invalid table name', str(context.exception))
    
    def test_multiple_tables_extraction(self):
        """Test that multiple tables are extracted correctly with proper quoting"""
        mock_connection, mock_cursor = self._create_mysql_mock()
        mock_cursor.fetchall.side_effect = [
            [{'id': 1}],  # users table
            [{'id': 2}],  # orders table
        ]
        
        tables = ['users', 'orders']
        results = list(self.extractor.extract_rows(mock_connection, tables))
        
        # Verify both tables were queried
        self.assertEqual(mock_cursor.execute.call_count, 2)
        
        # Verify both queries use proper quoting
        calls = mock_cursor.execute.call_args_list
        self.assertIn('`users`', calls[0][0][0])
        self.assertIn('`orders`', calls[1][0][0])
        
        # Verify results contain data from both tables
        self.assertEqual(len(results), 2)
    
    def test_sql_injection_union_attack_mysql(self):
        """Test that UNION-based SQL injection is prevented in MySQL"""
        mock_connection, mock_cursor = self._create_mysql_mock()
        
        # Attempt UNION injection to extract data from other tables
        malicious_table = "users UNION SELECT password FROM admin_users"
        tables = [malicious_table]
        list(self.extractor.extract_rows(mock_connection, tables))
        
        # Verify the UNION is escaped and treated as part of table name
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('`users UNION SELECT password FROM admin_users`', executed_query)
        # Should not contain unquoted UNION
        self.assertNotIn('UNION SELECT', executed_query.replace('`users UNION SELECT password FROM admin_users`', ''))
    
    def test_sql_injection_comment_attack_mysql(self):
        """Test that comment-based SQL injection is prevented in MySQL"""
        mock_connection, mock_cursor = self._create_mysql_mock()
        
        # Attempt to use comments to bypass security
        malicious_table = "users /* comment */ WHERE 1=1 --"
        tables = [malicious_table]
        list(self.extractor.extract_rows(mock_connection, tables))
        
        # Verify the entire string is quoted
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('`users /* comment */ WHERE 1=1 --`', executed_query)
    
    def test_sql_injection_stacked_queries_postgres(self):
        """Test that stacked queries are prevented in PostgreSQL"""
        mock_connection, mock_cursor = self._create_postgres_mock()
        
        # Attempt stacked queries
        malicious_table = "users; UPDATE users SET admin=true"
        tables = [malicious_table]
        list(self.extractor.extract_rows(mock_connection, tables))
        
        # Verify the entire string is quoted
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('"users; UPDATE users SET admin=true"', executed_query)
        # Verify no UPDATE statement is executed
        self.assertNotIn('UPDATE', executed_query.replace('"users; UPDATE users SET admin=true"', ''))
    
    def test_sql_injection_with_newlines(self):
        """Test that SQL injection with newlines is prevented"""
        mock_connection, mock_cursor = self._create_mysql_mock()
        
        # Attempt injection with newlines
        malicious_table = "users\nDROP TABLE users"
        tables = [malicious_table]
        list(self.extractor.extract_rows(mock_connection, tables))
        
        # Verify the entire string including newline is quoted
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('`users\nDROP TABLE users`', executed_query)
    
    def test_sql_injection_with_null_bytes(self):
        """Test that SQL injection with null bytes is prevented"""
        mock_connection, mock_cursor = self._create_mysql_mock()
        
        # Attempt injection with null byte
        malicious_table = "users\x00DROP TABLE users"
        tables = [malicious_table]
        list(self.extractor.extract_rows(mock_connection, tables))
        
        # Verify the entire string including null byte is quoted
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn(f'`users\x00DROP TABLE users`', executed_query)
    
    def test_table_name_with_special_chars_mysql(self):
        """Test that table names with special characters are properly handled in MySQL"""
        mock_connection, mock_cursor = self._create_mysql_mock()
        
        # Test various special characters that might appear in legitimate table names
        special_tables = [
            'user-data',
            'user.data',
            'user$data',
            'user@data',
        ]
        
        for table in special_tables:
            mock_cursor.reset_mock()
            list(self.extractor.extract_rows(mock_connection, [table]))
            executed_query = mock_cursor.execute.call_args[0][0]
            # Verify the table name is quoted
            self.assertIn(f'`{table}`', executed_query)
    
    def test_table_name_with_unicode_mysql(self):
        """Test that table names with unicode characters are properly handled"""
        mock_connection, mock_cursor = self._create_mysql_mock()
        
        # Test unicode table names
        unicode_table = 'users_日本語'
        list(self.extractor.extract_rows(mock_connection, [unicode_table]))
        
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn(f'`{unicode_table}`', executed_query)
    
    def test_empty_table_name_validation(self):
        """Test that empty table names are rejected"""
        mock_connection = Mock()
        mock_connection.__class__.__module__ = 'unknown.database'
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        
        # Empty table name should raise error
        tables = ['']
        
        with self.assertRaises(ValueError) as context:
            list(self.extractor.extract_rows(mock_connection, tables))
        
        self.assertIn('Invalid table name', str(context.exception))
    
    def test_whitespace_only_table_name_validation(self):
        """Test that whitespace-only table names are rejected"""
        mock_connection = Mock()
        mock_connection.__class__.__module__ = 'unknown.database'
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        
        # Whitespace-only table name should raise error
        tables = ['   ']
        
        with self.assertRaises(ValueError) as context:
            list(self.extractor.extract_rows(mock_connection, tables))
        
        self.assertIn('Invalid table name', str(context.exception))
    
    def test_sql_injection_with_hex_encoding(self):
        """Test that hex-encoded SQL injection attempts are prevented"""
        mock_connection, mock_cursor = self._create_mysql_mock()
        
        # Attempt injection with hex encoding
        malicious_table = "users WHERE 1=0x31"
        tables = [malicious_table]
        list(self.extractor.extract_rows(mock_connection, tables))
        
        # Verify the entire string is quoted
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('`users WHERE 1=0x31`', executed_query)
    
    def test_sql_injection_time_based_attack(self):
        """Test that time-based SQL injection is prevented"""
        mock_connection, mock_cursor = self._create_postgres_mock()
        
        # Attempt time-based injection
        malicious_table = "users; SELECT pg_sleep(10)"
        tables = [malicious_table]
        list(self.extractor.extract_rows(mock_connection, tables))
        
        # Verify the entire string is quoted
        executed_query = mock_cursor.execute.call_args[0][0]
        self.assertIn('"users; SELECT pg_sleep(10)"', executed_query)
    
    def test_multiple_backticks_escaping_mysql(self):
        """Test that multiple consecutive backticks are properly escaped"""
        mock_connection, mock_cursor = self._create_mysql_mock()
        
        # Table name with multiple backticks
        table = 'user``table'
        list(self.extractor.extract_rows(mock_connection, [table]))
        
        executed_query = mock_cursor.execute.call_args[0][0]
        # Each backtick should be doubled
        self.assertIn('`user````table`', executed_query)
    
    def test_multiple_quotes_escaping_postgres(self):
        """Test that multiple consecutive quotes are properly escaped"""
        mock_connection, mock_cursor = self._create_postgres_mock()
        
        # Table name with multiple quotes
        table = 'user""table'
        list(self.extractor.extract_rows(mock_connection, [table]))
        
        executed_query = mock_cursor.execute.call_args[0][0]
        # Each quote should be doubled
        self.assertIn('"user""""table"', executed_query)


if __name__ == '__main__':
    unittest.main()
