"""
Enhanced ClickHouse Client with Batch Insert Support
Optimized for high-throughput data loading
"""
import logging
import re
from typing import List, Dict, Any, Optional
from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseError

logger = logging.getLogger(__name__)


class ClickHouseClient:
    """
    Enhanced ClickHouse client with batch insert support and error handling.
    
    Features:
    - Batch inserts for performance
    - Connection pooling
    - Error recovery
    - Type-safe operations
    """

    def __init__(
        self,
        host,
        port=9000,
        user="etl_user",
        password="etl_pass123",
        database="etl",
        connect_timeout: int = 10,
        send_receive_timeout: int = 300,
        sync_request_timeout: int = 300,
        insert_retries: int = 3,
    ):
        """
        Initialize ClickHouse client using NATIVE protocol (clickhouse_driver).
        
        IMPORTANT: This uses the native TCP protocol which requires port 9000.
        This is DIFFERENT from HTTP queries which use port 8123.
        
        Args:
            host: ClickHouse host
            port: ClickHouse native protocol port (default: 9000)
            user: Username
            password: Password
            database: Database name
        """
        try:
            self.insert_retries = max(1, int(insert_retries))
            try:
                safe_db = self._sanitize_identifier(database, prefix="db")
                init_client = Client(
                    host=host,
                    port=port,
                    user=user,
                    password=password,
                    database="default",
                    connect_timeout=connect_timeout,
                    send_receive_timeout=send_receive_timeout,
                    sync_request_timeout=sync_request_timeout,
                )
                init_client.execute(f"CREATE DATABASE IF NOT EXISTS {self._quote_identifier(safe_db)}")
            except Exception:
                pass

            self.client = Client(
                host=host,
                port=port,
                user=user,
                password=password,
                database=self._sanitize_identifier(database, prefix="db"),
                connect_timeout=connect_timeout,
                send_receive_timeout=send_receive_timeout,
                sync_request_timeout=sync_request_timeout,
            )
            logger.info(f"[ClickHouse] Connected to {host}:{port}/{database}")
        except Exception as e:
            logger.error(f"[ClickHouse] Connection failed: {e}")
            raise

    @staticmethod
    def _sanitize_identifier(name: str, prefix: str = "c") -> str:
        value = str(name or "").strip()
        if not value:
            value = "column"
        safe = re.sub(r"[^a-zA-Z0-9_]", "_", value)
        safe = re.sub(r"_+", "_", safe)
        if not safe.strip("_"):
            safe = "column"
        if safe[0].isdigit():
            safe = f"{prefix}_{safe}"
        return safe

    @staticmethod
    def _quote_identifier(name: str) -> str:
        escaped = str(name).replace("`", "``")
        return f"`{escaped}`"

    def _quote_table(self, table: str) -> str:
        parts = [p for p in str(table).split(".") if p]
        if not parts:
            raise ValueError("Table name is required")
        safe_parts = [
            self._quote_identifier(self._sanitize_identifier(part, prefix="t"))
            for part in parts
        ]
        return ".".join(safe_parts)

    def _normalize_column_mapping(self, rows: List[Dict[str, Any]]) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        used: set[str] = set()
        for row in rows:
            for original in row.keys():
                original_name = str(original)
                if original_name in mapping:
                    continue
                base = self._sanitize_identifier(original_name, prefix="c")
                candidate = base
                suffix = 1
                while candidate in used:
                    suffix += 1
                    candidate = f"{base}_{suffix}"
                mapping[original_name] = candidate
                used.add(candidate)
        return mapping

    def insert_row(self, table: str, row: Dict[str, Any]):
        """
        Insert a single row into ClickHouse.
        
        Args:
            table: Table name
            row: Row dictionary
        """
        if not row:
            logger.warning(f"[ClickHouse] Empty row for table {table}")
            return
        
        try:
            table_sql = self._quote_table(table)
            mapping = self._normalize_column_mapping([row])
            normalized = {mapping[str(k)]: v for k, v in row.items()}
            columns = sorted(normalized.keys())
            columns_sql = ", ".join(self._quote_identifier(c) for c in columns)
            values = tuple(normalized.get(col) for col in columns)

            query = f"INSERT INTO {table_sql} ({columns_sql}) VALUES"
            self.client.execute(query, [values])
            
        except ClickHouseError as e:
            logger.error(f"[ClickHouse] Error inserting row into {table}: {e}")
            raise
        except Exception as e:
            logger.error(f"[ClickHouse] Unexpected error inserting row: {e}")
            raise

    def insert_batch(self, table: str, rows: List[Dict[str, Any]], batch_size: int = 1000):
        """
        Insert multiple rows in batch for better performance.
        
        Args:
            table: Table name
            rows: List of row dictionaries
            batch_size: Number of rows per batch (default: 1000)
            
        Returns:
            Number of rows successfully inserted
        """
        if not rows:
            return 0
        
        if not table:
            logger.error("[ClickHouse] Table name is required")
            return 0
        
        inserted_count = 0
        
        try:
            table_sql = self._quote_table(table)
            non_empty_rows = [row for row in rows if row]
            if not non_empty_rows:
                logger.warning(f"[ClickHouse] Empty rows for table {table}")
                return 0
            mapping = self._normalize_column_mapping(non_empty_rows)
            normalized_rows = [
                {mapping[str(k)]: v for k, v in row.items()}
                for row in non_empty_rows
            ]
            # Union of all keys across rows, stable deterministic ordering.
            columns = sorted({key for row in normalized_rows for key in row.keys()})
            columns_str = ", ".join(self._quote_identifier(column) for column in columns)
            
            # Process in batches
            for i in range(0, len(normalized_rows), batch_size):
                batch = normalized_rows[i:i + batch_size]
                
                # Prepare values for batch insert
                values_list = []
                for row in batch:
                    if not row:
                        continue
                    # Fill sparse values as None to preserve full column set.
                    values = tuple(row.get(col, None) for col in columns)
                    values_list.append(values)
                
                if not values_list:
                    continue
                
                # Execute batch insert
                query = f"INSERT INTO {table_sql} ({columns_str}) VALUES"
                attempts = 0
                while True:
                    try:
                        self.client.execute(query, values_list)
                        inserted_count += len(values_list)
                        break
                    except ClickHouseError:
                        attempts += 1
                        if attempts >= self.insert_retries:
                            raise
                
                logger.debug(f"[ClickHouse] Inserted batch of {len(values_list)} rows into {table}")
            
            logger.info(f"[ClickHouse] Successfully inserted {inserted_count} rows into {table}")
            return inserted_count
            
        except ClickHouseError as e:
            logger.error(f"[ClickHouse] Error inserting batch into {table}: {e}")
            raise
        except Exception as e:
            logger.error(f"[ClickHouse] Unexpected error inserting batch: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise

    def create_table(
        self,
        table: str,
        columns: Dict[str, str],
        engine: str = "MergeTree()",
        order_by: str = "tuple()",
        partition_by: Optional[str] = None,
        settings: Optional[str] = None,
    ):
        """
        Create a ClickHouse table with specified schema.
        
        Args:
            table: Table name
            columns: Dictionary of column_name: column_type
            engine: Table engine (default: MergeTree())
            order_by: ORDER BY clause (default: tuple())
        """
        try:
            table_sql = self._quote_table(table)
            safe_columns = {}
            used = set()
            for name, col_type in columns.items():
                base = self._sanitize_identifier(name, prefix="c")
                candidate = base
                suffix = 1
                while candidate in used:
                    suffix += 1
                    candidate = f"{base}_{suffix}"
                used.add(candidate)
                safe_columns[candidate] = col_type

            column_defs = ", ".join(
                [f"{self._quote_identifier(name)} {col_type}" for name, col_type in safe_columns.items()]
            )
            
            partition_clause = f"\n            PARTITION BY {partition_by}" if partition_by else ""
            settings_clause = f"\n            SETTINGS {settings}" if settings else ""
            create_query = f"""
            CREATE TABLE IF NOT EXISTS {table_sql} (
                {column_defs}
            ) ENGINE = {engine}
            {partition_clause}
            ORDER BY {order_by}
            {settings_clause}
            """
            
            self.client.execute(create_query)
            logger.info(f"[ClickHouse] Table {table} created/verified")
            
        except ClickHouseError as e:
            logger.error(f"[ClickHouse] Error creating table {table}: {e}")
            raise

    def drop_table(self, table: str) -> None:
        try:
            table_sql = self._quote_table(table)
            self.client.execute(f"DROP TABLE IF EXISTS {table_sql}")
            logger.info(f"[ClickHouse] Dropped table {table}")
        except Exception as e:
            logger.error(f"[ClickHouse] Error dropping table {table}: {e}")
            raise

    def create_table_like(self, new_table: str, source_table: str) -> None:
        try:
            new_table_sql = self._quote_table(new_table)
            source_table_sql = self._quote_table(source_table)
            self.client.execute(f"CREATE TABLE IF NOT EXISTS {new_table_sql} AS {source_table_sql}")
            logger.info(f"[ClickHouse] Created table {new_table} AS {source_table}")
        except Exception as e:
            logger.error(f"[ClickHouse] Error creating table {new_table} AS {source_table}: {e}")
            raise

    def rename_table(self, source_table: str, target_table: str) -> None:
        try:
            source_table_sql = self._quote_table(source_table)
            target_table_sql = self._quote_table(target_table)
            self.client.execute(f"RENAME TABLE {source_table_sql} TO {target_table_sql}")
            logger.info(f"[ClickHouse] Renamed table {source_table} to {target_table}")
        except Exception as e:
            logger.error(f"[ClickHouse] Error renaming table {source_table}: {e}")
            raise

    def count_rows(self, table: str) -> int:
        try:
            table_sql = self._quote_table(table)
            result = self.client.execute(f"SELECT COUNT(*) FROM {table_sql}")
            return int(result[0][0]) if result else 0
        except Exception as e:
            logger.error(f"[ClickHouse] Error counting rows in {table}: {e}")
            raise

    def insert_from_select(self, target_table: str, select_query: str) -> None:
        try:
            target_table_sql = self._quote_table(target_table)
            query = f"INSERT INTO {target_table_sql} {select_query}"
            self.client.execute(query)
        except Exception as e:
            logger.error(f"[ClickHouse] Error insert_from_select into {target_table}: {e}")
            raise

    def insert_from_select_dedup(self, target_table: str, staging_table: str, dedup_column: str) -> None:
        try:
            target_table_sql = self._quote_table(target_table)
            staging_table_sql = self._quote_table(staging_table)
            safe_dedup_column = self._quote_identifier(self._sanitize_identifier(dedup_column, prefix="c"))
            query = f"""
            INSERT INTO {target_table_sql}
            SELECT s.*
            FROM {staging_table_sql} AS s
            LEFT JOIN {target_table_sql} AS t
            ON s.{safe_dedup_column} = t.{safe_dedup_column}
            WHERE isNull(t.{safe_dedup_column})
            SETTINGS join_use_nulls = 1
            """
            self.client.execute(query)
        except Exception as e:
            logger.error(f"[ClickHouse] Error deduplicating insert from {staging_table} to {target_table}: {e}")
            raise

    def table_exists(self, table: str) -> bool:
        """
        Check if table exists.
        
        Args:
            table: Table name
            
        Returns:
            True if table exists, False otherwise
        """
        try:
            table_sql = self._quote_table(table)
            result = self.client.execute(f"EXISTS TABLE {table_sql}")
            return result[0][0] == 1
        except Exception as e:
            logger.error(f"[ClickHouse] Error checking table existence: {e}")
            return False

    def get_table_columns(self, table: str) -> List[str]:
        """
        Get list of column names for a table.
        
        Args:
            table: Table name
            
        Returns:
            List of column names
        """
        try:
            return list(self.get_table_schema(table).keys())
        except Exception as e:
            logger.error(f"[ClickHouse] Error getting columns for {table}: {e}")
            return []

    def get_table_schema(self, table: str) -> Dict[str, str]:
        try:
            table_sql = self._quote_table(table)
            result = self.client.execute(f"DESCRIBE TABLE {table_sql}")
            return {str(row[0]): str(row[1]) for row in result}
        except Exception as e:
            logger.error(f"[ClickHouse] Error getting schema for {table}: {e}")
            return {}

    def add_columns_if_missing(self, table: str, columns: Dict[str, str]) -> None:
        if not columns:
            return
        table_sql = self._quote_table(table)
        for name, col_type in columns.items():
            safe_name = self._sanitize_identifier(name, prefix="c")
            query = (
                f"ALTER TABLE {table_sql} "
                f"ADD COLUMN IF NOT EXISTS {self._quote_identifier(safe_name)} {col_type}"
            )
            self.client.execute(query)
