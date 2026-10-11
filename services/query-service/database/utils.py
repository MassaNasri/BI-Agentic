"""
Utility functions for database operations including ClickHouse cleanup.
"""
import requests
import logging
import re
from django.conf import settings

logger = logging.getLogger(__name__)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


def quote_clickhouse_identifier(value):
    value = str(value or '').strip()
    if not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError('Invalid ClickHouse identifier')
    return f'`{value}`'


def quote_clickhouse_string(value):
    """Return a ClickHouse single-quoted string literal.

    JSON double-quoted strings are not SQL string literals in current
    ClickHouse releases; they are parsed as identifiers. Backslash and quote
    escaping keeps metadata predicates valid without interpolating raw input.
    """
    escaped = str(value).replace('\\', '\\\\').replace("'", "\\'")
    return f"'{escaped}'"


def _safe_error(exc):
    return f'ClickHouse request failed ({type(exc).__name__})'


class ClickHouseClient:
    """Client for interacting with ClickHouse database."""
    
    def __init__(self):
        self.host = getattr(settings, 'CLICKHOUSE_HOST', 'localhost')
        self.port = getattr(settings, 'CLICKHOUSE_PORT', '8123')
        self.user = getattr(settings, 'CLICKHOUSE_USER', '')
        self.password = getattr(settings, 'CLICKHOUSE_PASSWORD', '')
        self.base_url = f'http://{self.host}:{self.port}'
    
    def execute_query(self, query):
        """Execute a query on ClickHouse."""
        try:
            auth = (self.user, self.password) if self.user else None
            response = requests.post(
                self.base_url,
                data=str(query).encode('utf-8'),
                auth=auth,
                timeout=(3, 10),
            )
            response.raise_for_status()
            return {'success': True, 'data': response.text}
        except Exception as e:
            safe_error = _safe_error(e)
            logger.error('%s', safe_error)
            return {'success': False, 'error': safe_error}
    
    def drop_table(self, database, table_name):
        """Drop a table from ClickHouse."""
        qualified = f"{quote_clickhouse_identifier(database)}.{quote_clickhouse_identifier(table_name)}"
        query = f"DROP TABLE IF EXISTS {qualified}"
        logger.info('Dropping ClickHouse table for authorized dataset')
        result = self.execute_query(query)
        if result['success']:
            logger.info('Successfully dropped authorized dataset table')
        else:
            logger.error(f"Failed to drop table: {result.get('error')}")
        return result
    
    def get_table_preview(self, database, table_name, limit=5):
        """Get preview data from a ClickHouse table."""
        limit = max(1, min(int(limit), 100))
        qualified = f"{quote_clickhouse_identifier(database)}.{quote_clickhouse_identifier(table_name)}"
        query = f"SELECT * FROM {qualified} LIMIT {limit} FORMAT JSONEachRow"
        result = self.execute_query(query)
        
        if result['success']:
            try:
                import json
                rows = [json.loads(line) for line in result['data'].strip().split('\n') if line]
                return {'success': True, 'rows': rows}
            except Exception as e:
                logger.error(f"Error parsing ClickHouse response: {str(e)}")
                return {'success': False, 'error': str(e)}
        
        return result
    
    def get_table_schema(self, database, table_name):
        """Get schema information for a table."""
        qualified = f"{quote_clickhouse_identifier(database)}.{quote_clickhouse_identifier(table_name)}"
        query = f"DESCRIBE TABLE {qualified} FORMAT JSONEachRow"
        result = self.execute_query(query)
        
        if result['success']:
            try:
                import json
                schema = [json.loads(line) for line in result['data'].strip().split('\n') if line]
                return {'success': True, 'schema': schema}
            except Exception as e:
                logger.error(f"Error parsing schema: {str(e)}")
                return {'success': False, 'error': str(e)}
        
        return result
    
    def get_table_count(self, database, table_name):
        """Get row count for a table."""
        qualified = f"{quote_clickhouse_identifier(database)}.{quote_clickhouse_identifier(table_name)}"
        query = f"SELECT COUNT(*) as count FROM {qualified} FORMAT JSONEachRow"
        result = self.execute_query(query)
        
        if result['success']:
            try:
                import json
                data = json.loads(result['data'].strip())
                return {'success': True, 'count': data.get('count', 0)}
            except Exception as e:
                logger.error(f"Error getting table count: {str(e)}")
                return {'success': False, 'error': str(e)}
        
        return result
    
    def table_exists(self, database, table_name):
        """Check if a table exists in ClickHouse."""
        database_value = str(database or '').strip()
        table_value = str(table_name or '').strip()
        quote_clickhouse_identifier(database_value)
        quote_clickhouse_identifier(table_value)
        query = (
            'SELECT count() FROM system.tables WHERE database = '
            f'{quote_clickhouse_string(database_value)} '
            f'AND name = {quote_clickhouse_string(table_value)}'
        )
        result = self.execute_query(query)
        
        if result['success']:
            try:
                count = int(result['data'].strip())
                return {'success': True, 'exists': count == 1}
            except Exception as e:
                logger.error(f"Error checking table existence: {str(e)}")
                return {'success': False, 'error': str(e)}
        
        return result
    
    def get_all_tables(self, database='default'):
        """Get list of all tables in a database."""
        database_value = str(database or '').strip()
        quote_clickhouse_identifier(database_value)
        query = (
            'SELECT name FROM system.tables WHERE database = '
            f'{quote_clickhouse_string(database_value)} FORMAT JSONEachRow'
        )
        result = self.execute_query(query)
        
        if result['success']:
            try:
                import json
                tables = [json.loads(line)['name'] for line in result['data'].strip().split('\n') if line]
                return {'success': True, 'tables': tables}
            except Exception as e:
                logger.error(f"Error getting tables: {str(e)}")
                return {'success': False, 'error': str(e)}
        
        return result


def format_file_size(size_bytes):
    """Format file size in human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def cleanup_database(database_instance):
    """
    Cleanup all resources associated with a database instance.
    This includes ClickHouse tables and any other related data.
    """
    cleanup_results = {
        'clickhouse_dropped': False,
        'errors': []
    }
    
    # Drop every allowlisted destination for a multi-table snapshot. Legacy
    # datasets still contribute clickhouse_table_name as their only target.
    table_names = []
    for imported in getattr(database_instance, 'source_tables', None) or []:
        if isinstance(imported, dict) and imported.get('destination_table'):
            table_names.append(str(imported['destination_table']))
    if database_instance.clickhouse_table_name:
        table_names.append(str(database_instance.clickhouse_table_name))
    table_names = list(dict.fromkeys(table_names))
    cleanup_results['clickhouse_tables'] = []
    if table_names:
        clickhouse = ClickHouseClient()
        for table_name in table_names:
            result = clickhouse.drop_table(database_instance.clickhouse_database, table_name)
            cleanup_results['clickhouse_tables'].append({
                'table': table_name,
                'dropped': bool(result['success']),
            })
            if not result['success']:
                cleanup_results['errors'].append(f"ClickHouse: {result.get('error')}")
        cleanup_results['clickhouse_dropped'] = not cleanup_results['errors']
    
    return cleanup_results

