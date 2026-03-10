"""
Initialize ClickHouse tables for ETL pipeline.
This script creates the necessary tables for idempotency and data quality tracking.
"""
import os
import sys
import logging
from clickhouse_driver import Client
from clickhouse_schemas import ClickHouseSchemaManager
from ch_identifiers import quote_identifier, sanitize_identifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_clickhouse_config():
    """Get ClickHouse configuration from environment variables."""
    return {
        'host': os.getenv('CLICKHOUSE_HOST', 'localhost'),
        'port': int(os.getenv('CLICKHOUSE_PORT', 9000)),
        'user': os.getenv('CLICKHOUSE_USER', 'default'),
        'password': os.getenv('CLICKHOUSE_PASSWORD', ''),
        'database': sanitize_identifier(os.getenv('CLICKHOUSE_DATABASE', 'etl'), prefix="db", fallback="etl"),
    }


def init_tables():
    """Initialize all required ClickHouse tables."""
    config = get_clickhouse_config()
    
    logger.info(f"Connecting to ClickHouse at {config['host']}:{config['port']}")
    
    try:
        # Create database if it doesn't exist
        init_client = Client(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database='default'
        )
        init_client.execute(f"CREATE DATABASE IF NOT EXISTS {quote_identifier(config['database'])}")
        logger.info(f"Database '{config['database']}' created/verified")
        
        # Connect to the ETL database
        client = Client(
            host=config['host'],
            port=config['port'],
            user=config['user'],
            password=config['password'],
            database=config['database']
        )
        
        # Initialize schema manager
        schema_manager = ClickHouseSchemaManager(client)
        
        # Create deduplication_log table
        logger.info("Creating deduplication_log table...")
        if schema_manager.create_deduplication_log_table():
            logger.info("✓ deduplication_log table created successfully")
            
            # Verify table exists
            if schema_manager.table_exists('deduplication_log'):
                logger.info("✓ Table existence verified")
                
                # Display schema
                schema = schema_manager.get_table_schema('deduplication_log')
                if schema:
                    logger.info("Table schema:")
                    for col_name, col_type in schema:
                        logger.info(f"  - {col_name}: {col_type}")
            else:
                logger.error("✗ Table verification failed")
                return False
        else:
            logger.error("✗ Failed to create deduplication_log table")
            return False
        
        logger.info("\n✓ All tables initialized successfully")
        return True
        
    except Exception as e:
        logger.error(f"✗ Error initializing tables: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


if __name__ == '__main__':
    success = init_tables()
    sys.exit(0 if success else 1)
