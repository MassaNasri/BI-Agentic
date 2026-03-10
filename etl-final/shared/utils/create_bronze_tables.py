"""
Bronze Table Creation Script
Creates bronze layer tables in ClickHouse for different data sources.

This script implements FR-1 (Immutable Raw Layer) and US-2 (Immutable raw data storage)
from the ETL architecture redesign spec.

Usage:
    # As a standalone script
    python create_bronze_tables.py --source customers --columns id,name,email
    
    # As a module
    from create_bronze_tables import BronzeTableCreator
    creator = BronzeTableCreator()
    creator.create_table("customers", ["id", "name", "email"])
"""
import os
import sys
import logging
import argparse
from typing import List, Dict, Optional
from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseError

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from models.bronze_schema import BronzeTableSchema
from clickhouse_schemas import ClickHouseSchemaManager
from ch_identifiers import quote_identifier, sanitize_identifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BronzeTableCreator:
    """
    Creates and manages bronze layer tables in ClickHouse.
    
    Provides methods to create bronze tables for different data sources
    with proper error handling and validation.
    """
    
    def __init__(self, client: Optional[Client] = None):
        """
        Initialize bronze table creator.
        
        Args:
            client: Optional ClickHouse client. If not provided, creates one from environment.
        """
        if client:
            self.client = client
        else:
            self.client = self._create_client_from_env()
        
        self.schema_manager = ClickHouseSchemaManager(self.client)
    
    def _create_client_from_env(self) -> Client:
        """
        Create ClickHouse client from environment variables.
        
        Environment variables:
            CLICKHOUSE_HOST: ClickHouse host (default: localhost)
            CLICKHOUSE_PORT: ClickHouse port (default: 9000)
            CLICKHOUSE_USER: ClickHouse user (default: default)
            CLICKHOUSE_PASSWORD: ClickHouse password (default: empty)
            CLICKHOUSE_DATABASE: ClickHouse database (default: etl)
        
        Returns:
            ClickHouse client instance
        """
        config = {
            'host': os.getenv('CLICKHOUSE_HOST', 'localhost'),
            'port': int(os.getenv('CLICKHOUSE_PORT', 9000)),
            'user': os.getenv('CLICKHOUSE_USER', 'default'),
            'password': os.getenv('CLICKHOUSE_PASSWORD', ''),
            'database': sanitize_identifier(os.getenv('CLICKHOUSE_DATABASE', 'etl'), prefix="db", fallback="etl"),
        }
        
        logger.info(f"Connecting to ClickHouse at {config['host']}:{config['port']}/{config['database']}")
        
        try:
            # Ensure database exists
            init_client = Client(
                host=config['host'],
                port=config['port'],
                user=config['user'],
                password=config['password'],
                database='default'
            )
            init_client.execute(f"CREATE DATABASE IF NOT EXISTS {quote_identifier(config['database'])}")
            logger.info(f"Database '{config['database']}' verified")
            
            # Connect to the ETL database
            return Client(
                host=config['host'],
                port=config['port'],
                user=config['user'],
                password=config['password'],
                database=config['database']
            )
        except Exception as e:
            logger.error(f"Failed to connect to ClickHouse: {e}")
            raise
    
    def create_table(
        self,
        source_name: str,
        columns: List[str],
        partition_by: Optional[str] = None,
        order_by: Optional[List[str]] = None,
        settings: Optional[Dict] = None
    ) -> bool:
        """
        Create a bronze table for a data source.
        
        Args:
            source_name: Name of the data source (e.g., 'customers', 'orders')
            columns: List of data column names
            partition_by: Optional custom partitioning strategy
            order_by: Optional custom ordering columns
            settings: Optional ClickHouse table settings
        
        Returns:
            True if table created successfully, False otherwise
        """
        if not source_name:
            logger.error("source_name cannot be empty")
            return False
        
        if not columns:
            logger.error("columns list cannot be empty")
            return False
        
        try:
            # Create schema definition
            data_columns = {col: "String" for col in columns}
            schema = BronzeTableSchema(
                source_name=source_name,
                data_columns=data_columns
            )
            
            # Apply custom settings if provided
            if partition_by:
                schema.partition_by = partition_by
            if order_by:
                schema.order_by = order_by
            if settings:
                schema.settings = settings
            
            # Create the table
            logger.info(f"Creating bronze table for source '{source_name}' with {len(columns)} columns")
            result = self.schema_manager.create_bronze_table(schema)
            
            if result:
                logger.info(f"✓ Bronze table '{schema.table_name}' created successfully")
                self._display_table_info(schema.table_name)
            else:
                logger.error(f"✗ Failed to create bronze table '{schema.table_name}'")
            
            return result
            
        except Exception as e:
            logger.error(f"Error creating bronze table for '{source_name}': {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def create_table_from_schema(self, schema: BronzeTableSchema) -> bool:
        """
        Create a bronze table from a BronzeTableSchema object.
        
        Args:
            schema: BronzeTableSchema object defining the table structure
        
        Returns:
            True if table created successfully, False otherwise
        """
        try:
            logger.info(f"Creating bronze table '{schema.table_name}'")
            result = self.schema_manager.create_bronze_table(schema)
            
            if result:
                logger.info(f"✓ Bronze table '{schema.table_name}' created successfully")
                self._display_table_info(schema.table_name)
            else:
                logger.error(f"✗ Failed to create bronze table '{schema.table_name}'")
            
            return result
            
        except Exception as e:
            logger.error(f"Error creating bronze table: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def create_multiple_tables(self, table_definitions: List[Dict]) -> Dict[str, bool]:
        """
        Create multiple bronze tables from a list of definitions.
        
        Args:
            table_definitions: List of dictionaries with keys:
                - source_name: Name of the data source
                - columns: List of column names
                - partition_by: Optional partitioning strategy
                - order_by: Optional ordering columns
                - settings: Optional table settings
        
        Returns:
            Dictionary mapping source_name to creation success status
        """
        results = {}
        
        for definition in table_definitions:
            source_name = definition.get('source_name')
            if not source_name:
                logger.warning("Skipping table definition without source_name")
                continue
            
            columns = definition.get('columns', [])
            partition_by = definition.get('partition_by')
            order_by = definition.get('order_by')
            settings = definition.get('settings')
            
            result = self.create_table(
                source_name=source_name,
                columns=columns,
                partition_by=partition_by,
                order_by=order_by,
                settings=settings
            )
            results[source_name] = result
        
        # Summary
        success_count = sum(1 for v in results.values() if v)
        total_count = len(results)
        logger.info(f"\nCreated {success_count}/{total_count} bronze tables successfully")
        
        return results
    
    def table_exists(self, source_name: str) -> bool:
        """
        Check if a bronze table exists for a data source.
        
        Args:
            source_name: Name of the data source
        
        Returns:
            True if table exists, False otherwise
        """
        table_name = f"bronze_{source_name}"
        return self.schema_manager.table_exists(table_name)
    
    def get_table_schema(self, source_name: str) -> Optional[list]:
        """
        Get the schema of a bronze table.
        
        Args:
            source_name: Name of the data source
        
        Returns:
            List of tuples (column_name, column_type) or None if error
        """
        table_name = f"bronze_{source_name}"
        return self.schema_manager.get_table_schema(table_name)
    
    def _display_table_info(self, table_name: str):
        """Display information about a created table."""
        try:
            schema = self.schema_manager.get_table_schema(table_name)
            if schema:
                logger.info(f"Table schema for '{table_name}':")
                
                # Group columns by type
                lineage_cols = []
                data_cols = []
                metadata_cols = []
                
                for col_name, col_type in schema:
                    if col_name.startswith('_') and not col_name.startswith('_file'):
                        lineage_cols.append((col_name, col_type))
                    elif col_name.startswith('_file') or col_name == '_row_number':
                        metadata_cols.append((col_name, col_type))
                    else:
                        data_cols.append((col_name, col_type))
                
                if lineage_cols:
                    logger.info("  Lineage columns:")
                    for col_name, col_type in lineage_cols:
                        logger.info(f"    - {col_name}: {col_type}")
                
                if data_cols:
                    logger.info("  Data columns:")
                    for col_name, col_type in data_cols:
                        logger.info(f"    - {col_name}: {col_type}")
                
                if metadata_cols:
                    logger.info("  Metadata columns:")
                    for col_name, col_type in metadata_cols:
                        logger.info(f"    - {col_name}: {col_type}")
        except Exception as e:
            logger.warning(f"Could not display table info: {e}")


def main():
    """Main entry point for standalone script execution."""
    parser = argparse.ArgumentParser(
        description='Create bronze layer tables in ClickHouse',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create a single table
  python create_bronze_tables.py --source customers --columns id,name,email,phone
  
  # Create a table with custom partitioning
  python create_bronze_tables.py --source events --columns event_id,event_type,timestamp \\
      --partition-by "toYYYYMMDD(_extracted_at)"
  
  # Create multiple tables from a config file
  python create_bronze_tables.py --config tables_config.json
        """
    )
    
    parser.add_argument(
        '--source',
        type=str,
        help='Name of the data source (e.g., customers, orders)'
    )
    
    parser.add_argument(
        '--columns',
        type=str,
        help='Comma-separated list of column names'
    )
    
    parser.add_argument(
        '--partition-by',
        type=str,
        help='Custom partitioning strategy (default: toYYYYMM(_extracted_at))'
    )
    
    parser.add_argument(
        '--order-by',
        type=str,
        help='Comma-separated list of ordering columns (default: _batch_id,_row_id)'
    )
    
    parser.add_argument(
        '--config',
        type=str,
        help='Path to JSON config file with multiple table definitions'
    )
    
    parser.add_argument(
        '--check',
        type=str,
        help='Check if a bronze table exists for the given source name'
    )
    
    args = parser.parse_args()
    
    try:
        creator = BronzeTableCreator()
        
        # Check mode
        if args.check:
            exists = creator.table_exists(args.check)
            if exists:
                logger.info(f"✓ Bronze table for '{args.check}' exists")
                schema = creator.get_table_schema(args.check)
                if schema:
                    logger.info(f"Table has {len(schema)} columns")
                sys.exit(0)
            else:
                logger.info(f"✗ Bronze table for '{args.check}' does not exist")
                sys.exit(1)
        
        # Config file mode
        if args.config:
            import json
            with open(args.config, 'r') as f:
                config = json.load(f)
            
            table_definitions = config.get('tables', [])
            if not table_definitions:
                logger.error("Config file must contain 'tables' array")
                sys.exit(1)
            
            results = creator.create_multiple_tables(table_definitions)
            success = all(results.values())
            sys.exit(0 if success else 1)
        
        # Single table mode
        if not args.source or not args.columns:
            parser.print_help()
            sys.exit(1)
        
        columns = [col.strip() for col in args.columns.split(',')]
        order_by = [col.strip() for col in args.order_by.split(',')] if args.order_by else None
        
        success = creator.create_table(
            source_name=args.source,
            columns=columns,
            partition_by=args.partition_by,
            order_by=order_by
        )
        
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        logger.info("\nOperation cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == '__main__':
    main()
