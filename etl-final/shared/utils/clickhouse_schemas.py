"""
ClickHouse Schema Definitions for ETL Pipeline
Implements Medallion Architecture (Bronze/Silver/Gold) with idempotency support
"""
import logging
from typing import Optional, Dict, List
from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseError
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from models.bronze_schema import BronzeTableSchema
from .ch_identifiers import quote_table_name

logger = logging.getLogger(__name__)


class ClickHouseSchemaManager:
    """
    Manages ClickHouse table schemas for the ETL pipeline.
    
    Implements:
    - Deduplication table for idempotent operations
    - Bronze layer (raw data)
    - Silver layer (cleaned data)
    - Quarantine table (invalid data)
    """
    
    def __init__(self, client: Client):
        """
        Initialize schema manager with ClickHouse client.
        
        Args:
            client: ClickHouse client instance
        """
        self.client = client
    
    def create_deduplication_log_table(self) -> bool:
        """
        Create deduplication_log table for tracking processed data.
        
        Schema based on design.md section 5.4:
        - _dedup_key: SHA256 hash for deduplication
        - _batch_id: Batch identifier
        - _stage: Pipeline stage (extract, transform, load)
        - _processed_at: Processing timestamp
        - _row_id: UUID of the processed row
        
        Uses ReplacingMergeTree to automatically deduplicate based on _dedup_key and _stage.
        The latest _processed_at value is kept for each unique (_dedup_key, _stage) pair.
        
        Returns:
            True if table created successfully, False otherwise
        """
        create_query = """
        CREATE TABLE IF NOT EXISTS deduplication_log (
            _dedup_key String,
            _batch_id String,
            _stage String,
            _processed_at DateTime64(3),
            _row_id UUID
        ) ENGINE = ReplacingMergeTree(_processed_at)
        PARTITION BY toYYYYMM(_processed_at)
        ORDER BY (_dedup_key, _stage)
        """
        
        try:
            self.client.execute(create_query)
            logger.info("[ClickHouse] deduplication_log table created/verified")
            return True
        except ClickHouseError as e:
            logger.error(f"[ClickHouse] Error creating deduplication_log table: {e}")
            return False
        except Exception as e:
            logger.error(f"[ClickHouse] Unexpected error creating deduplication_log table: {e}")
            return False
    
    def table_exists(self, table_name: str) -> bool:
        """
        Check if a table exists in ClickHouse.
        
        Args:
            table_name: Name of the table to check
            
        Returns:
            True if table exists, False otherwise
        """
        try:
            quoted_table = quote_table_name(table_name)
            result = self.client.execute(f"EXISTS TABLE {quoted_table}")
            return result[0][0] == 1
        except Exception as e:
            logger.error(f"[ClickHouse] Error checking table existence: {e}")
            return False
    
    def get_table_schema(self, table_name: str) -> Optional[list]:
        """
        Get the schema of a table.
        
        Args:
            table_name: Name of the table
            
        Returns:
            List of tuples (column_name, column_type) or None if error
        """
        try:
            quoted_table = quote_table_name(table_name)
            result = self.client.execute(f"DESCRIBE TABLE {quoted_table}")
            return [(row[0], row[1]) for row in result]
        except Exception as e:
            logger.error(f"[ClickHouse] Error getting table schema: {e}")
            return None
    
    def create_bronze_table(self, schema: BronzeTableSchema) -> bool:
        """
        Create a bronze layer table using the provided schema definition.
        
        Bronze tables store immutable raw data with comprehensive lineage tracking.
        All data columns are initially stored as String type to preserve original format.
        
        Args:
            schema: BronzeTableSchema object defining the table structure
            
        Returns:
            True if table created successfully, False otherwise
        """
        try:
            create_sql = schema.get_create_table_sql()
            self.client.execute(create_sql)
            logger.info(f"[ClickHouse] Bronze table '{schema.table_name}' created/verified")
            return True
        except ClickHouseError as e:
            logger.error(f"[ClickHouse] Error creating bronze table '{schema.table_name}': {e}")
            return False
        except Exception as e:
            logger.error(f"[ClickHouse] Unexpected error creating bronze table '{schema.table_name}': {e}")
            return False
    
    def create_bronze_table_from_columns(self, source_name: str, columns: List[str]) -> bool:
        """
        Create a bronze layer table from a list of column names.
        
        Convenience method that creates a BronzeTableSchema and calls create_bronze_table.
        All columns are created as String type initially.
        
        Args:
            source_name: Name of the data source (e.g., 'customers', 'orders')
            columns: List of column names
            
        Returns:
            True if table created successfully, False otherwise
        """
        # Create schema with all columns as String type
        data_columns = {col: "String" for col in columns}
        schema = BronzeTableSchema(
            source_name=source_name,
            data_columns=data_columns
        )
        return self.create_bronze_table(schema)

    def create_quarantine_table(self, table_name: str = "quarantine") -> bool:
        """
        Create quarantine table for invalid rows.

        Schema based on design.md section 5.3:
        - _quarantine_id: Unique ID
        - _row_id: Original row ID (UUID)
        - _batch_id: Batch identifier
        - _source_id: Source identifier
        - _quarantined_at: Timestamp
        - _quarantine_reason: Reason for quarantine
        - _validation_errors: Validation errors
        - _original_row: JSON serialized original row
        - _reprocessed: Whether row has been reprocessed

        Returns:
            True if table created successfully, False otherwise
        """
        safe_table = quote_table_name(table_name)
        create_query = f"""
        CREATE TABLE IF NOT EXISTS {safe_table} (
            _quarantine_id UUID DEFAULT generateUUIDv4(),
            _row_id UUID,
            _batch_id String,
            _source_id String,
            _quarantined_at DateTime64(3),
            _quarantine_reason String,
            _validation_errors Array(String),
            _original_row String,
            _reprocessed Bool DEFAULT false
        ) ENGINE = MergeTree()
        PARTITION BY toYYYYMM(_quarantined_at)
        ORDER BY (_quarantined_at, _quarantine_id)
        """

        try:
            self.client.execute(create_query)
            logger.info("[ClickHouse] %s table created/verified", table_name)
            return True
        except ClickHouseError as e:
            logger.error("[ClickHouse] Error creating %s table: %s", table_name, e)
            return False
        except Exception as e:
            logger.error("[ClickHouse] Unexpected error creating %s table: %s", table_name, e)
            return False

    def create_quality_metrics_table(self, table_name: str = "quality_metrics") -> bool:
        """
        Create quality_metrics table for batch-level quality tracking.
        """
        safe_table = quote_table_name(table_name)
        create_query = f"""
        CREATE TABLE IF NOT EXISTS {safe_table} (
            _metric_id UUID DEFAULT generateUUIDv4(),
            _batch_id String,
            _source_id String,
            _calculated_at DateTime64(3),
            _row_count UInt64,
            _completeness_score Float32,
            _validity_score Float32,
            _consistency_score Float32,
            _quality_score Float32
        ) ENGINE = MergeTree()
        PARTITION BY toYYYYMM(_calculated_at)
        ORDER BY (_calculated_at, _source_id, _batch_id)
        """
        try:
            self.client.execute(create_query)
            logger.info("[ClickHouse] %s table created/verified", table_name)
            return True
        except ClickHouseError as e:
            logger.error("[ClickHouse] Error creating %s table: %s", table_name, e)
            return False
        except Exception as e:
            logger.error("[ClickHouse] Unexpected error creating %s table: %s", table_name, e)
            return False

    def create_quality_anomalies_table(self, table_name: str = "quality_anomalies") -> bool:
        """
        Create quality_anomalies table for anomaly detection results.
        """
        safe_table = quote_table_name(table_name)
        create_query = f"""
        CREATE TABLE IF NOT EXISTS {safe_table} (
            _anomaly_id UUID DEFAULT generateUUIDv4(),
            _batch_id String,
            _source_id String,
            _detected_at DateTime64(3),
            _metric String,
            _value Float32,
            _baseline Float32,
            _stddev Float32,
            _zscore Float32
        ) ENGINE = MergeTree()
        PARTITION BY toYYYYMM(_detected_at)
        ORDER BY (_detected_at, _source_id, _batch_id)
        """
        try:
            self.client.execute(create_query)
            logger.info("[ClickHouse] %s table created/verified", table_name)
            return True
        except ClickHouseError as e:
            logger.error("[ClickHouse] Error creating %s table: %s", table_name, e)
            return False
        except Exception as e:
            logger.error("[ClickHouse] Unexpected error creating %s table: %s", table_name, e)
            return False

    def create_schema_contract_registry_table(self, table_name: str = "schema_contract_registry") -> bool:
        """
        Create schema contract registry table for persistent contract resolution.
        """
        safe_table = quote_table_name(table_name)
        create_query = f"""
        CREATE TABLE IF NOT EXISTS {safe_table} (
            source_id String,
            schema_version String,
            schema_id String,
            contract_json String,
            updated_at DateTime64(3)
        ) ENGINE = ReplacingMergeTree(updated_at)
        PARTITION BY toYYYYMM(updated_at)
        ORDER BY (source_id, schema_version, schema_id)
        """
        try:
            self.client.execute(create_query)
            logger.info("[ClickHouse] %s table created/verified", table_name)
            return True
        except ClickHouseError as e:
            logger.error("[ClickHouse] Error creating %s table: %s", table_name, e)
            return False
        except Exception as e:
            logger.error("[ClickHouse] Unexpected error creating %s table: %s", table_name, e)
            return False
