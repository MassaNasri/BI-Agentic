"""
SQL Guard Service

Enforces read-only SQL execution and workspace isolation.
CRITICAL SECURITY COMPONENT - Never skip validation.
"""

import re
import logging
from typing import Dict, List, Tuple

from query_api.utils import normalize_sql_table_references

logger = logging.getLogger(__name__)


class SQLGuard:
    """
    SQL Guard enforces:
    1. Read-only queries (SELECT only)
    2. Workspace database isolation  
    3. No dangerous SQL operations
    4. Syntax validation
    """
    
    # Allowed SQL operations (read-only)
    ALLOWED_OPERATIONS = ['SELECT']
    
    # Blocked SQL keywords (write/admin operations)
    BLOCKED_KEYWORDS = [
        'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'TRUNCATE',
        'CREATE', 'RENAME', 'REPLACE', 'GRANT', 'REVOKE',
        'EXECUTE', 'EXEC', 'CALL', 'PROCEDURE', 'FUNCTION',
        'INTO OUTFILE', 'INTO DUMPFILE', 'LOAD DATA',
        'SHOW GRANTS', 'SHOW USERS', 'SHOW PROCESSLIST',
    ]
    
    # Dangerous patterns
    DANGEROUS_PATTERNS = [
        r';\s*DROP',  # SQL injection attempt
        r';\s*DELETE',
        r';\s*UPDATE',
        r'--\s*',  # SQL comments (potential injection)
        r'/\*.*?\*/',  # Multi-line comments
        r'UNION\s+SELECT',  # Union-based injection
        r'@@',  # System variables
        r'BENCHMARK\s*\(',  # Timing attacks
        r'SLEEP\s*\(',  # DOS attacks
    ]
    
    def __init__(self, workspace_database=None):
        """
        Initialize SQL Guard.
        
        Args:
            workspace_database: Database name for workspace isolation
        """
        self.workspace_database = workspace_database
    
    def validate_sql(self, sql: str) -> Tuple[bool, str, Dict]:
        """
        Validate SQL query for security and correctness.
        
        Args:
            sql: SQL query to validate
        
        Returns:
            tuple: (is_valid, error_message, validation_details)
        """
        try:
            # Clean SQL
            sql_clean = sql.strip()
            
            if not sql_clean:
                return False, "SQL query is empty", {}
            
            # Convert to uppercase for keyword matching
            sql_upper = sql_clean.upper()
            
            validation_details = {
                'original_sql': sql,
                'checks_passed': [],
                'checks_failed': []
            }
            
            # Check 1: Must start with SELECT
            if not sql_upper.startswith('SELECT'):
                validation_details['checks_failed'].append('Must start with SELECT')
                return False, "Only SELECT queries are allowed", validation_details
            
            validation_details['checks_passed'].append('Starts with SELECT')
            
            # Check 2: Block dangerous keywords
            for keyword in self.BLOCKED_KEYWORDS:
                if re.search(r'\b' + keyword + r'\b', sql_upper):
                    validation_details['checks_failed'].append(f'Blocked keyword: {keyword}')
                    return False, f"Blocked keyword detected: {keyword}", validation_details
            
            validation_details['checks_passed'].append('No blocked keywords')
            
            # Check 3: Block dangerous patterns
            for pattern in self.DANGEROUS_PATTERNS:
                if re.search(pattern, sql_upper, re.IGNORECASE):
                    validation_details['checks_failed'].append(f'Dangerous pattern: {pattern}')
                    return False, "Dangerous SQL pattern detected", validation_details
            
            validation_details['checks_passed'].append('No dangerous patterns')
            
            # Check 4: Validate database reference if workspace isolation enabled
            if self.workspace_database:
                # If query specifies database, it must match workspace database
                db_match = re.findall(r'FROM\s+([a-zA-Z0-9_]+)\.', sql_upper)
                if db_match:
                    for db in db_match:
                        if db.lower() != self.workspace_database.lower():
                            validation_details['checks_failed'].append(
                                f'Wrong database: {db} (expected {self.workspace_database})'
                            )
                            return False, f"Database mismatch: {db}", validation_details
                
                validation_details['checks_passed'].append('Database isolation check passed')
            
            # Check 5: Basic syntax validation (simple checks)
            if sql_clean.count('(') != sql_clean.count(')'):
                validation_details['checks_failed'].append('Unbalanced parentheses')
                return False, "Unbalanced parentheses in SQL", validation_details
            
            validation_details['checks_passed'].append('Syntax check passed')
            
            # All checks passed
            logger.info(f"SQL validation passed: {len(validation_details['checks_passed'])} checks")
            return True, "SQL validation passed", validation_details
        
        except Exception as e:
            logger.error(f"SQL validation error: {e}")
            return False, f"Validation error: {str(e)}", {}
    
    def sanitize_sql(self, sql: str) -> str:
        """
        Sanitize SQL by removing comments and normalizing whitespace.
        
        Args:
            sql: SQL query
        
        Returns:
            str: Sanitized SQL
        """
        try:
            # Remove single-line comments
            sql = re.sub(r'--.*?$', '', sql, flags=re.MULTILINE)
            
            # Remove multi-line comments
            sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.DOTALL)
            
            # Normalize whitespace
            sql = ' '.join(sql.split())
            
            return sql.strip()
        
        except Exception as e:
            logger.error(f"SQL sanitization error: {e}")
            return sql
    
    def enforce_workspace_database(self, sql: str) -> str:
        """
        Ensure all table references use workspace database.
        
        Args:
            sql: SQL query
        
        Returns:
            str: SQL with workspace database enforced
        """
        if not self.workspace_database:
            return sql
        
        try:
            # Deterministic normalization prevents malformed references such as:
            # etl.etl.table -> etl.table
            sql_modified = normalize_sql_table_references(sql, self.workspace_database)
            return sql_modified
        
        except Exception as e:
            logger.error(f"Failed to enforce workspace database: {e}")
            return sql
    
    def validate_and_sanitize(self, sql: str) -> Tuple[bool, str, str]:
        """
        Combined validation and sanitization.
        
        Args:
            sql: SQL query
        
        Returns:
            tuple: (is_valid, error_message, sanitized_sql)
        """
        # Sanitize first
        sanitized = self.sanitize_sql(sql)
        
        # Validate sanitized SQL
        is_valid, error_msg, details = self.validate_sql(sanitized)
        
        if not is_valid:
            return False, error_msg, sanitized
        
        # Enforce workspace database
        final_sql = self.enforce_workspace_database(sanitized)
        
        return True, "Validation passed", final_sql


class SQLGuardFactory:
    """Factory for creating SQL Guards with workspace isolation."""
    
    @staticmethod
    def create_for_workspace(workspace):
        """
        Create SQL Guard for specific workspace.
        
        Args:
            workspace: Workspace model instance
        
        Returns:
            SQLGuard: Configured SQL Guard
        """
        # Use workspace-specific database name
        # This could be derived from workspace ID or configured per workspace
        workspace_database = 'etl'  # Default ClickHouse database
        
        return SQLGuard(workspace_database=workspace_database)
    
    @staticmethod
    def create_default():
        """Create SQL Guard with no workspace isolation."""
        return SQLGuard()


# Convenience functions
def validate_sql(sql: str, workspace=None) -> Tuple[bool, str]:
    """
    Quick validation function.
    
    Args:
        sql: SQL query
        workspace: Optional workspace for isolation
    
    Returns:
        tuple: (is_valid, error_message)
    """
    if workspace:
        guard = SQLGuardFactory.create_for_workspace(workspace)
    else:
        guard = SQLGuardFactory.create_default()
    
    is_valid, error_msg, _ = guard.validate_and_sanitize(sql)
    return is_valid, error_msg


def sanitize_and_validate_sql(sql: str, workspace=None) -> Tuple[bool, str, str]:
    """
    Sanitize and validate SQL.
    
    Args:
        sql: SQL query
        workspace: Optional workspace for isolation
    
    Returns:
        tuple: (is_valid, error_message, sanitized_sql)
    """
    if workspace:
        guard = SQLGuardFactory.create_for_workspace(workspace)
    else:
        guard = SQLGuardFactory.create_default()
    
    return guard.validate_and_sanitize(sql)

