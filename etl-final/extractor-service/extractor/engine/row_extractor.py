class RowExtractor:
    def __init__(self):
        import os
        self.fetch_size = int(os.getenv("EXTRACTOR_FETCH_SIZE", "1000"))

    def _to_row_dict(self, row, columns):
        if isinstance(row, dict):
            return row
        if columns and isinstance(row, (list, tuple)) and len(columns) == len(row):
            return dict(zip(columns, row))
        return {"data": str(row)}

    def extract_rows(self, connection, tables: list):
        cursor = connection.cursor()

        for table in tables:
            # Use proper identifier quoting to prevent SQL injection
            # Note: Table names cannot be parameterized like values, so we use identifier quoting
            # The table names come from database metadata queries (SHOW TABLES, pg_tables)
            # which are trusted, but we still quote them for safety
            
            # Detect database type from connection or cursor
            connection_type = type(connection).__module__
            cursor_type = type(cursor).__module__
            
            # Check both connection and cursor types for database identification
            if 'pymysql' in connection_type or 'pymysql' in cursor_type or 'MySQLdb' in connection_type:
                # MySQL uses backticks for identifier quoting
                quoted_table = f"`{table.replace('`', '``')}`"
            elif 'psycopg' in connection_type or 'psycopg' in cursor_type:
                # PostgreSQL uses double quotes for identifier quoting
                safe_table = table.replace('"', '""')
                quoted_table = f'"{safe_table}"'
            else:
                # Fallback: validate table name contains only safe characters
                import re
                if not re.match(r'^[a-zA-Z0-9_]+$', table):
                    raise ValueError(f"Invalid table name: {table}")
                quoted_table = table
            
            query = f"SELECT * FROM {quoted_table}"
            cursor.execute(query)
            columns = [desc[0] for desc in (cursor.description or [])]

            # Prefer streaming reads; fall back to fetchall for legacy cursor mocks.
            while True:
                rows = cursor.fetchmany(self.fetch_size)
                if not isinstance(rows, (list, tuple)):
                    rows = cursor.fetchall()
                    for row in rows:
                        yield table, self._to_row_dict(row, columns)
                    break
                if not rows:
                    break
                for row in rows:
                    yield table, self._to_row_dict(row, columns)
