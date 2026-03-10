"""
Loader Logic for ClickHouse Operations
Provides high-level interface for data loading operations
"""
import logging
import time
from typing import List, Dict, Any
from uuid import uuid4
from shared.utils.circuit_breaker import CircuitBreaker
from .clickhouse_client import ClickHouseClient

logger = logging.getLogger(__name__)


class LoaderLogic:
    """
    High-level loader logic for ClickHouse operations.
    
    Features:
    - Single row inserts
    - Batch inserts
    - Table management
    - Error handling
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize loader logic using ClickHouse native protocol.
        
        IMPORTANT: Uses clickhouse_driver (native TCP protocol on port 9000).
        This is DIFFERENT from HTTP queries which use port 8123.
        
        Args:
            config: Configuration dictionary with ClickHouse connection details
        """
        self.client = ClickHouseClient(
            host=config.get("host", "clickhouse"),
            port=config.get("port", 9000),  # Native protocol port
            user=config.get("user", "default"),
            password=config.get("password", ""),
            database=config.get("database", "default"),
            connect_timeout=int(config.get("connect_timeout", 10)),
            send_receive_timeout=int(config.get("send_receive_timeout", 300)),
            sync_request_timeout=int(config.get("sync_request_timeout", 300)),
            insert_retries=int(config.get("insert_retries", 3)),
        )
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=int(config.get("circuit_breaker_threshold", 5)),
            recovery_time=int(config.get("circuit_breaker_recovery", 30)),
        )

    def load_row(self, table: str, row: Dict[str, Any]):
        """
        Load a single row into ClickHouse.
        
        Args:
            table: Table name
            row: Row dictionary
        """
        self.client.insert_row(table, row)

    def load_batch(self, table: str, rows: List[Dict[str, Any]], batch_size: int = 1000) -> int:
        """
        Load multiple rows in batch.
        
        Args:
            table: Table name
            rows: List of row dictionaries
            batch_size: Batch size for inserts
            
        Returns:
            Number of rows successfully inserted
        """
        return self.client.insert_batch(table, rows, batch_size)

    def load_batch_resilient(
        self,
        table: str,
        rows: List[Dict[str, Any]],
        batch_size: int = 1000,
        transactional: bool = True,
        retries: int = 3,
        backoff_base: float = 0.5,
        max_backoff: float = 5.0,
    ) -> int:
        """
        Load a batch with circuit breaker and retry/backoff protection.
        """
        if not self.circuit_breaker.allow():
            raise Exception("Circuit breaker open for ClickHouse")

        attempt = 0
        while True:
            try:
                if transactional:
                    inserted = self.load_batch_transactional(
                        table,
                        rows,
                        batch_size=batch_size,
                        retries=0,
                        backoff_base=backoff_base,
                        max_backoff=max_backoff,
                    )
                else:
                    inserted = self.load_batch(table, rows, batch_size=batch_size)
                self.circuit_breaker.record_success()
                return inserted
            except Exception:
                self.circuit_breaker.record_failure()
                attempt += 1
                if attempt > retries:
                    raise
                backoff = min(max_backoff, backoff_base * (2 ** (attempt - 1)))
                time.sleep(backoff)

    def load_batch_transactional(
        self,
        table: str,
        rows: List[Dict[str, Any]],
        batch_size: int = 1000,
        retries: int = 3,
        backoff_base: float = 0.5,
        max_backoff: float = 5.0,
    ) -> int:
        """
        Transactional-like loading using staging table + insert_from_select.
        """
        if not self.circuit_breaker.allow():
            raise Exception("Circuit breaker open for ClickHouse")

        attempt = 0
        while True:
            staging_table = f"{table}_staging_{uuid4().hex[:8]}"
            staging_created = False
            try:
                if self.client.table_exists(table):
                    self.client.create_table_like(staging_table, table)
                    staging_created = True
                else:
                    # Create staging with same schema as target (fallback)
                    columns = {
                        key: "String"
                        for row in rows
                        for key in row.keys()
                    }
                    self.client.create_table(staging_table, columns)
                    staging_created = True

                inserted = self.client.insert_batch(staging_table, rows, batch_size)
                count = self.client.count_rows(staging_table)
                if count != inserted:
                    raise Exception("Row count mismatch in staging")

                if self.client.table_exists(table):
                    if any("_transformed_dedup_key" in row for row in rows):
                        self.client.insert_from_select_dedup(
                            target_table=table,
                            staging_table=staging_table,
                            dedup_column="_transformed_dedup_key",
                        )
                    else:
                        self.client.insert_from_select(table, f"SELECT * FROM {staging_table}")
                    self.client.drop_table(staging_table)
                else:
                    # Atomic commit for brand-new tables
                    self.client.rename_table(staging_table, table)
                self.circuit_breaker.record_success()
                return inserted
            except Exception:
                self.circuit_breaker.record_failure()
                if staging_created:
                    try:
                        self.client.drop_table(staging_table)
                    except Exception:
                        pass
                attempt += 1
                if attempt > retries:
                    raise
                backoff = min(max_backoff, backoff_base * (2 ** (attempt - 1)))
                time.sleep(backoff)
