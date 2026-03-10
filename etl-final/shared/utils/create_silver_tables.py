"""
Silver Table Creation Script
Creates silver layer tables in ClickHouse for different data sources.

This script implements FR-2 (Staging Layer) and US-7 (Data Quality Metrics)
from the ETL architecture redesign spec.

Usage:
    # As a standalone script
    python create_silver_tables.py --source customers --schema customers_schema.json
    
    # As a module
    from create_silver_tables import SilverTableCreator
    creator = SilverTableCreator()
    creator.create_table_from_schema(customer_schema)
"""
import os
import sys
import logging
import argparse
import json
from typing import List, Dict, Optional
from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseError

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from models.silver_schema import (
    SilverTableSchema,
    SilverColumnDefinition,
    DataType
)
from .ch_identifiers import (
    quote_identifier,
    quote_table_name,
    sanitize_identifier,
    sanitize_identifier_map,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SilverTableCreator:
    """
    Creates and manages silver layer tables in ClickHouse.
    
    Provides methods to create silver tables for different data sources
    with proper type mapping, quality columns, and lineage tracking.
    """
    
    def __init__(self, client: Optional[Client] = None):
        """
        Initialize silver table creator.
        
        Args:
            client: Optional ClickHouse client. If not provided, creates one from environment.
        """
        if client:
            self.client = client
        else:
            self.client = self._create_client_from_env()
        self.column_name_mappings: Dict[str, Dict[str, str]] = {}
    
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
            'database': sanitize_identifier(
                os.getenv('CLICKHOUSE_DATABASE', 'etl'),
                prefix="db",
                fallback="etl",
            ),
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
    
    def create_table_from_schema(self, schema: SilverTableSchema) -> bool:
        """
        Create a silver table from a SilverTableSchema object.
        
        Args:
            schema: SilverTableSchema object defining the table structure
        
        Returns:
            True if table created successfully, False otherwise
        """
        try:
            schema = self._sanitize_schema(schema)
            logger.info(f"Creating silver table '{schema.table_name}'")
            
            # Generate CREATE TABLE SQL
            create_sql = schema.get_create_table_sql()
            
            # Execute the SQL
            self.client.execute(create_sql)
            
            logger.info(f"✓ Silver table '{schema.table_name}' created successfully")
            self._display_table_info(schema)
            
            return True
            
        except ClickHouseError as e:
            logger.error(f"ClickHouse error creating silver table '{schema.table_name}': {e}")
            return False
        except Exception as e:
            logger.error(f"Error creating silver table '{schema.table_name}': {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    
    def create_table_from_json(self, json_path: str) -> bool:
        """
        Create a silver table from a JSON schema definition file.
        
        JSON format:
        {
            "source_name": "customers",
            "data_columns": [
                {
                    "name": "customer_id",
                    "data_type": "INT64",
                    "nullable": false,
                    "comment": "Customer identifier"
                },
                ...
            ],
            "partition_by": "toYYYYMM(_cleaned_at)",
            "order_by": ["_batch_id", "_row_id"],
            "settings": {"index_granularity": 8192}
        }
        
        Args:
            json_path: Path to JSON schema definition file
        
        Returns:
            True if table created successfully, False otherwise
        """
        try:
            with open(json_path, 'r') as f:
                schema_dict = json.load(f)
            
            schema = self._parse_schema_dict(schema_dict)
            return self.create_table_from_schema(schema)
            
        except FileNotFoundError:
            logger.error(f"Schema file not found: {json_path}")
            return False
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in schema file: {e}")
            return False
        except Exception as e:
            logger.error(f"Error loading schema from JSON: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def create_multiple_tables(self, schema_definitions: List[Dict]) -> Dict[str, bool]:
        """
        Create multiple silver tables from a list of schema definitions.
        
        Args:
            schema_definitions: List of dictionaries with schema definitions
        
        Returns:
            Dictionary mapping source_name to creation success status
        """
        results = {}
        
        for schema_dict in schema_definitions:
            source_name = schema_dict.get('source_name')
            if not source_name:
                logger.warning("Skipping schema definition without source_name")
                continue
            
            try:
                schema = self._parse_schema_dict(schema_dict)
                result = self.create_table_from_schema(schema)
                results[source_name] = result
            except Exception as e:
                logger.error(f"Error creating table for '{source_name}': {e}")
                results[source_name] = False
        
        # Summary
        success_count = sum(1 for v in results.values() if v)
        total_count = len(results)
        logger.info(f"\nCreated {success_count}/{total_count} silver tables successfully")
        
        return results
    
    def table_exists(self, source_name: str) -> bool:
        """
        Check if a silver table exists for a data source.
        
        Args:
            source_name: Name of the data source
        
        Returns:
            True if table exists, False otherwise
        """
        table_name = quote_table_name(f"silver_{source_name}")
        try:
            result = self.client.execute(f"EXISTS TABLE {table_name}")
            return result[0][0] == 1
        except Exception as e:
            logger.error(f"Error checking if table exists: {e}")
            return False
    
    def get_table_schema(self, source_name: str) -> Optional[list]:
        """
        Get the schema of a silver table.
        
        Args:
            source_name: Name of the data source
        
        Returns:
            List of tuples (column_name, column_type) or None if error
        """
        table_name = quote_table_name(f"silver_{source_name}")
        try:
            result = self.client.execute(f"DESCRIBE TABLE {table_name}")
            return [(row[0], row[1]) for row in result]
        except Exception as e:
            logger.error(f"Error getting table schema: {e}")
            return None
    
    def drop_table(self, source_name: str) -> bool:
        """
        Drop a silver table.
        
        Args:
            source_name: Name of the data source
        
        Returns:
            True if table dropped successfully, False otherwise
        """
        table_name = quote_table_name(f"silver_{source_name}")
        try:
            logger.warning(f"Dropping silver table '{table_name}'")
            self.client.execute(f"DROP TABLE IF EXISTS {table_name}")
            logger.info(f"✓ Silver table '{table_name}' dropped successfully")
            return True
        except Exception as e:
            logger.error(f"Error dropping table: {e}")
            return False
    
    def _parse_schema_dict(self, schema_dict: Dict) -> SilverTableSchema:
        """
        Parse a dictionary into a SilverTableSchema object.
        
        Args:
            schema_dict: Dictionary with schema definition
        
        Returns:
            SilverTableSchema object
        """
        source_name = schema_dict.get('source_name')
        if not source_name:
            raise ValueError("source_name is required")
        safe_source_name = sanitize_identifier(source_name, prefix="src", fallback="source")
        
        # Parse data columns
        data_columns = []
        raw_names = [str(col.get('name') or "") for col in schema_dict.get('data_columns', [])]
        mapping = sanitize_identifier_map(raw_names, prefix="c", fallback="column")
        self.column_name_mappings[safe_source_name] = mapping
        for col_dict in schema_dict.get('data_columns', []):
            col_name = col_dict.get('name')
            if not col_name:
                raise ValueError("Column name is required")
            safe_col_name = mapping[str(col_name)]
            if safe_col_name != col_name:
                logger.info("Normalized silver column '%s' -> '%s'", col_name, safe_col_name)
            
            # Parse data type
            data_type_str = col_dict.get('data_type', 'STRING')
            try:
                data_type = DataType[data_type_str]
            except KeyError:
                logger.warning(f"Unknown data type '{data_type_str}', using STRING")
                data_type = DataType.STRING
            
            column = SilverColumnDefinition(
                name=safe_col_name,
                data_type=data_type,
                nullable=col_dict.get('nullable', False),
                default_value=col_dict.get('default_value'),
                comment=col_dict.get('comment', '')
            )
            data_columns.append(column)
        
        # Create schema
        schema = SilverTableSchema(
            source_name=safe_source_name,
            data_columns=data_columns
        )
        
        # Apply optional settings
        if 'partition_by' in schema_dict:
            schema.partition_by = schema_dict['partition_by']
        
        if 'order_by' in schema_dict:
            schema.order_by = schema_dict['order_by']
        
        if 'settings' in schema_dict:
            schema.settings = schema_dict['settings']
        
        if 'indexes' in schema_dict:
            schema.indexes = schema_dict['indexes']
        
        return schema

    def _sanitize_schema(self, schema: SilverTableSchema) -> SilverTableSchema:
        """
        Return a sanitized schema copy for safe SQL generation.
        """
        safe_source = sanitize_identifier(schema.source_name, prefix="src", fallback="source")
        mapping = sanitize_identifier_map(
            [col.name for col in schema.data_columns],
            prefix="c",
            fallback="column",
        )
        self.column_name_mappings[safe_source] = mapping

        safe_columns = []
        for col in schema.data_columns:
            safe_col_name = mapping[str(col.name)]
            if safe_col_name != col.name:
                logger.info("Normalized silver column '%s' -> '%s'", col.name, safe_col_name)
            safe_columns.append(
                SilverColumnDefinition(
                    name=safe_col_name,
                    data_type=col.data_type,
                    nullable=col.nullable,
                    default_value=col.default_value,
                    comment=col.comment,
                )
            )

        return SilverTableSchema(
            source_name=safe_source,
            data_columns=safe_columns,
            partition_by=schema.partition_by,
            order_by=schema.order_by,
            settings=schema.settings,
            indexes=schema.indexes,
        )
    
    def _display_table_info(self, schema: SilverTableSchema):
        """Display information about a created table."""
        try:
            logger.info(f"Table schema for '{schema.table_name}':")
            
            # Lineage columns
            logger.info("  Lineage columns:")
            logger.info("    - _row_id: UUID")
            logger.info("    - _bronze_row_id: UUID")
            logger.info("    - _batch_id: String")
            logger.info("    - _cleaned_at: DateTime64(3)")
            logger.info("    - _cleaning_version: String")
            
            # Data columns
            if schema.data_columns:
                logger.info("  Data columns:")
                for col in schema.data_columns:
                    nullable_str = " (nullable)" if col.nullable else ""
                    logger.info(f"    - {col.name}: {col.data_type.value}{nullable_str}")
            
            # Quality metadata columns
            logger.info("  Quality metadata columns:")
            logger.info("    - _quality_score: Float32")
            logger.info("    - _applied_rules: Array(String)")
            logger.info("    - _warnings: Array(String)")
            logger.info("    - _completeness_score: Float32")
            logger.info("    - _validity_score: Float32")
            
            # Indexes
            if schema.indexes:
                logger.info("  Indexes:")
                for idx in schema.indexes:
                    logger.info(f"    - {idx['name']} on {idx['column']} ({idx['type']})")
            
            # Partitioning and ordering
            logger.info(f"  Partitioning: {schema.partition_by}")
            logger.info(f"  Ordering: {', '.join(schema.order_by)}")
            
        except Exception as e:
            logger.warning(f"Could not display table info: {e}")


def main():
    """Main entry point for standalone script execution."""
    parser = argparse.ArgumentParser(
        description='Create silver layer tables in ClickHouse',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create a table from JSON schema
  python create_silver_tables.py --schema customers_schema.json
  
  # Create multiple tables from a config file
  python create_silver_tables.py --config silver_tables_config.json
  
  # Check if a table exists
  python create_silver_tables.py --check customers
  
  # Drop a table
  python create_silver_tables.py --drop customers
        """
    )
    
    parser.add_argument(
        '--schema',
        type=str,
        help='Path to JSON schema definition file'
    )
    
    parser.add_argument(
        '--config',
        type=str,
        help='Path to JSON config file with multiple table definitions'
    )
    
    parser.add_argument(
        '--check',
        type=str,
        help='Check if a silver table exists for the given source name'
    )
    
    parser.add_argument(
        '--drop',
        type=str,
        help='Drop a silver table for the given source name'
    )
    
    args = parser.parse_args()
    
    try:
        creator = SilverTableCreator()
        
        # Check mode
        if args.check:
            exists = creator.table_exists(args.check)
            if exists:
                logger.info(f"✓ Silver table for '{args.check}' exists")
                schema = creator.get_table_schema(args.check)
                if schema:
                    logger.info(f"Table has {len(schema)} columns")
                sys.exit(0)
            else:
                logger.info(f"✗ Silver table for '{args.check}' does not exist")
                sys.exit(1)
        
        # Drop mode
        if args.drop:
            success = creator.drop_table(args.drop)
            sys.exit(0 if success else 1)
        
        # Config file mode
        if args.config:
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
        if args.schema:
            success = creator.create_table_from_json(args.schema)
            sys.exit(0 if success else 1)
        
        # No arguments provided
        parser.print_help()
        sys.exit(1)
        
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
