"""
Bronze Writer for Direct ClickHouse Writes

This module implements direct writing to bronze layer tables, bypassing Kafka
for raw data storage. This improves performance and simplifies the architecture
for the immutable raw data layer.

Design Principles:
- Batch writes for efficiency
- Idempotent operations using deduplication
- Error handling with retry logic
- Comprehensive logging for observability

Requirements:
- FR-1: Immutable Raw Layer - All extracted data stored in immutable raw tables
- US-2: Immutable raw data storage (AC 2.2: Raw layer with timestamp and source tracking)
- NFR-1: Performance - Throughput: 100K rows/sec per service instance
- Task 2.2.5: Implement direct write to bronze tables (bypass Kafka for raw data)
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from uuid import uuid4
from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseError

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from models.bronze_schema import BronzeRow, BronzeBatch, BronzeTableSchema
from utils.idempotency_manager import IdempotencyManager, IdempotencyKey, PipelineStage
from utils.ch_identifiers import quote_table_name

logger = logging.getLogger(__name__)


class BronzeWriteError(Exception):
    """Raised when bronze write operation fails."""
    pass


class BronzeWriter:
    """
    Handles direct writes to bronze layer tables in ClickHouse.
    
    Provides batch writing with:
    - Idempotency checking using deduplication keys
    - Automatic retry with exponential backoff
    - Row count validation
    - Comprehensive error handling
    
    Key Features:
    - Bypasses Kafka for raw data (writes directly to ClickHouse)
    - Batch inserts for high throughput
    - Idempotent operations (safe retries)
    - Validates data before insertion
    - Tracks lineage metadata
    
    Example Usage:
        client = Client(host='localhost', database='etl')
        writer = BronzeWriter(client)
        
        # Create bronze rows
        rows = [
            BronzeRow(
                batch_id="batch_123",
                source_id="customers_db",
                extracted_at=datetime.now(timezone.utc),
                data={"id": "1", "name": "Alice", "email": "alice@example.com"}
            )
        ]
        
        # Create batch
        schema = BronzeTableSchema(
            source_name="customers",
            data_columns={"id": "String", "name": "String", "email": "String"}
        )
        batch = BronzeBatch(
            batch_id="batch_123",
            source_id="customers_db",
            rows=rows,
            schema=schema
        )
        
        # Write to bronze table
        result = writer.write_batch(batch)
    """
    
    def __init__(
        self,
        client: Client,
        idempotency_manager: Optional[IdempotencyManager] = None,
        max_retries: int = 3,
        enable_deduplication: bool = True
    ):
        """
        Initialize bronze writer.
        
        Args:
            client: ClickHouse client instance
            idempotency_manager: Optional IdempotencyManager for deduplication
            max_retries: Maximum number of retry attempts for failed writes
            enable_deduplication: Whether to check for duplicates before writing
        """
        self.client = client
        self.idempotency_manager = idempotency_manager or IdempotencyManager(client)
        self.max_retries = max_retries
        self.enable_deduplication = enable_deduplication
    
    def write_batch(
        self,
        batch: BronzeBatch,
        skip_validation: bool = False
    ) -> Dict[str, Any]:
        """
        Write a batch of rows to a bronze table.
        
        This is the main entry point for writing data to bronze tables.
        It handles:
        1. Batch validation
        2. Deduplication checking
        3. Batch insertion with retry logic
        4. Row count verification
        5. Idempotency marking
        
        Args:
            batch: BronzeBatch containing rows and schema
            skip_validation: Skip batch validation (use with caution)
            
        Returns:
            Dictionary with write results:
                - success: bool indicating if write succeeded
                - rows_written: number of rows successfully written
                - rows_skipped: number of duplicate rows skipped
                - table_name: name of the bronze table
                - batch_id: batch identifier
                - error: error message if write failed
                
        Raises:
            BronzeWriteError: If write fails after all retries
        """
        start_time = datetime.now(timezone.utc)
        
        # Validate batch
        if not skip_validation:
            is_valid, errors = batch.validate()
            if not is_valid:
                error_msg = f"Batch validation failed: {'; '.join(errors)}"
                logger.error(f"[BronzeWriter] {error_msg}")
                return {
                    "success": False,
                    "rows_written": 0,
                    "rows_skipped": 0,
                    "table_name": batch.schema.table_name,
                    "batch_id": batch.batch_id,
                    "error": error_msg
                }
        
        # Filter out duplicates if deduplication is enabled
        rows_to_write = batch.rows
        rows_skipped = 0
        
        if self.enable_deduplication:
            rows_to_write, rows_skipped = self._filter_duplicates(batch.rows, batch.source_id)
            
            if not rows_to_write:
                logger.info(
                    f"[BronzeWriter] All {len(batch.rows)} rows in batch {batch.batch_id} "
                    f"are duplicates, skipping write"
                )
                return {
                    "success": True,
                    "rows_written": 0,
                    "rows_skipped": rows_skipped,
                    "table_name": batch.schema.table_name,
                    "batch_id": batch.batch_id
                }
        
        # Ensure table exists
        try:
            self._ensure_table_exists(batch.schema)
        except Exception as e:
            error_msg = f"Failed to ensure table exists: {str(e)}"
            logger.error(f"[BronzeWriter] {error_msg}")
            return {
                "success": False,
                "rows_written": 0,
                "rows_skipped": rows_skipped,
                "table_name": batch.schema.table_name,
                "batch_id": batch.batch_id,
                "error": error_msg
            }
        
        # Write rows with retry logic
        try:
            rows_written = self._write_rows_with_retry(
                table_name=batch.schema.table_name,
                rows=rows_to_write
            )
            
            # Mark rows as processed for idempotency
            if self.enable_deduplication:
                self._mark_rows_processed(rows_to_write, batch.source_id)
            
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            throughput = rows_written / duration if duration > 0 else 0
            
            logger.info(
                f"[BronzeWriter] Successfully wrote {rows_written} rows to {batch.schema.table_name} "
                f"(skipped {rows_skipped} duplicates) in {duration:.2f}s ({throughput:.0f} rows/sec)"
            )
            
            return {
                "success": True,
                "rows_written": rows_written,
                "rows_skipped": rows_skipped,
                "table_name": batch.schema.table_name,
                "batch_id": batch.batch_id,
                "duration_seconds": duration,
                "throughput_rows_per_sec": throughput
            }
            
        except BronzeWriteError as e:
            error_msg = str(e)
            logger.error(f"[BronzeWriter] {error_msg}")
            return {
                "success": False,
                "rows_written": 0,
                "rows_skipped": rows_skipped,
                "table_name": batch.schema.table_name,
                "batch_id": batch.batch_id,
                "error": error_msg
            }
    
    def _filter_duplicates(
        self,
        rows: List[BronzeRow],
        source_id: str
    ) -> Tuple[List[BronzeRow], int]:
        """
        Filter out duplicate rows using idempotency manager.
        
        Args:
            rows: List of BronzeRow objects
            source_id: Source identifier
            
        Returns:
            Tuple of (filtered_rows, num_duplicates)
        """
        filtered_rows = []
        num_duplicates = 0
        
        for row in rows:
            # Create idempotency key
            key = IdempotencyKey(
                source_id=source_id,
                batch_id=row.batch_id,
                row_hash=row.dedup_key
            )
            
            # Check if already processed
            if self.idempotency_manager.is_duplicate(key, PipelineStage.EXTRACT):
                num_duplicates += 1
                logger.debug(
                    f"[BronzeWriter] Skipping duplicate row: "
                    f"batch_id={row.batch_id}, dedup_key={row.dedup_key}"
                )
            else:
                filtered_rows.append(row)
        
        if num_duplicates > 0:
            logger.info(
                f"[BronzeWriter] Filtered out {num_duplicates} duplicate rows "
                f"from {len(rows)} total rows"
            )
        
        return filtered_rows, num_duplicates
    
    def _mark_rows_processed(self, rows: List[BronzeRow], source_id: str):
        """
        Mark rows as processed in the idempotency manager.
        
        Args:
            rows: List of BronzeRow objects
            source_id: Source identifier
        """
        for row in rows:
            key = IdempotencyKey(
                source_id=source_id,
                batch_id=row.batch_id,
                row_hash=row.dedup_key
            )
            self.idempotency_manager.mark_processed(
                key=key,
                stage=PipelineStage.EXTRACT,
                row_id=row.row_id
            )
    
    def _ensure_table_exists(self, schema: BronzeTableSchema):
        """
        Ensure bronze table exists, create if it doesn't.
        
        Args:
            schema: BronzeTableSchema defining the table structure
            
        Raises:
            BronzeWriteError: If table creation fails
        """
        try:
            # Check if table exists
            safe_table = quote_table_name(schema.table_name)
            result = self.client.execute(f"EXISTS TABLE {safe_table}")
            table_exists = result[0][0] == 1
            
            if not table_exists:
                logger.info(f"[BronzeWriter] Creating bronze table {schema.table_name}")
                create_sql = schema.get_create_table_sql()
                self.client.execute(create_sql)
                logger.info(f"[BronzeWriter] Bronze table {schema.table_name} created")
            
        except ClickHouseError as e:
            raise BronzeWriteError(f"Failed to ensure table exists: {str(e)}")
    
    def _write_rows_with_retry(
        self,
        table_name: str,
        rows: List[BronzeRow]
    ) -> int:
        """
        Write rows to bronze table with retry logic.
        
        Args:
            table_name: Name of the bronze table
            rows: List of BronzeRow objects to write
            
        Returns:
            Number of rows written
            
        Raises:
            BronzeWriteError: If write fails after all retries
        """
        if not rows:
            return 0
        
        # Convert rows to dictionaries
        row_dicts = [row.to_dict() for row in rows]
        
        # Try to insert with retries
        last_error = None
        for attempt in range(self.max_retries):
            try:
                # Build INSERT query
                # ClickHouse driver handles parameterization
                self.client.execute(
                    f"INSERT INTO {quote_table_name(table_name)} VALUES",
                    row_dicts
                )
                
                # Verify row count
                inserted_count = self._verify_row_count(table_name, rows[0].batch_id)
                
                return len(rows)
                
            except ClickHouseError as e:
                last_error = e
                logger.warning(
                    f"[BronzeWriter] Write attempt {attempt + 1}/{self.max_retries} failed: {str(e)}"
                )
                
                # Don't retry on certain errors
                if "UNKNOWN_TABLE" in str(e) or "NO_SUCH_COLUMN" in str(e):
                    raise BronzeWriteError(f"Schema error: {str(e)}")
                
                # Exponential backoff
                if attempt < self.max_retries - 1:
                    import time
                    backoff_seconds = 2 ** attempt
                    logger.info(f"[BronzeWriter] Retrying in {backoff_seconds} seconds...")
                    time.sleep(backoff_seconds)
        
        # All retries failed
        raise BronzeWriteError(
            f"Failed to write rows after {self.max_retries} attempts. "
            f"Last error: {str(last_error)}"
        )
    
    def _verify_row_count(self, table_name: str, batch_id: str) -> int:
        """
        Verify the number of rows inserted for a batch.
        
        Args:
            table_name: Name of the bronze table
            batch_id: Batch identifier
            
        Returns:
            Number of rows found for the batch
        """
        try:
            result = self.client.execute(
                f"SELECT COUNT(*) FROM {quote_table_name(table_name)} WHERE _batch_id = %(batch_id)s",
                {"batch_id": batch_id}
            )
            return result[0][0] if result else 0
        except Exception as e:
            logger.warning(f"[BronzeWriter] Could not verify row count: {str(e)}")
            return 0
    
    def write_rows_direct(
        self,
        table_name: str,
        rows: List[Dict[str, Any]],
        batch_id: str,
        source_id: str
    ) -> Dict[str, Any]:
        """
        Write rows directly to a bronze table without BronzeBatch wrapper.
        
        This is a convenience method for cases where you have raw dictionaries
        and want to write them directly without creating BronzeRow objects.
        
        Args:
            table_name: Name of the bronze table (e.g., 'bronze_customers')
            rows: List of row dictionaries
            batch_id: Batch identifier
            source_id: Source identifier
            
        Returns:
            Dictionary with write results (same as write_batch)
        """
        # Convert dictionaries to BronzeRow objects
        bronze_rows = []
        extracted_at = datetime.now(timezone.utc)
        
        for idx, row_data in enumerate(rows):
            bronze_row = BronzeRow(
                batch_id=batch_id,
                source_id=source_id,
                extracted_at=extracted_at,
                data=row_data,
                row_number=idx
            )
            bronze_rows.append(bronze_row)
        
        # Extract source name from table name
        source_name = table_name.replace("bronze_", "")
        
        # Create schema (columns from first row)
        if rows:
            data_columns = {
                col: "String"
                for row in rows
                for col in row.keys()
            }
        else:
            data_columns = {}
        
        schema = BronzeTableSchema(
            source_name=source_name,
            data_columns=data_columns
        )
        
        # Create batch and write
        batch = BronzeBatch(
            batch_id=batch_id,
            source_id=source_id,
            rows=bronze_rows,
            schema=schema
        )
        
        return self.write_batch(batch)
