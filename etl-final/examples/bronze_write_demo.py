"""
Bronze Write Example - Demonstrates BronzeWriter functionality
"""

import sys
import os
from datetime import datetime, timezone
from uuid import uuid4

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared'))

from clickhouse_driver import Client
from models.bronze_schema import BronzeRow, BronzeBatch, BronzeTableSchema
from utils.bronze_writer import BronzeWriter


def main():
    """Demonstrate bronze write functionality."""
    print("Bronze Writer Demo")
    print("=" * 60)
    
    # Create ClickHouse client
    client = Client(
        host=os.getenv('CLICKHOUSE_HOST', 'localhost'),
        port=int(os.getenv('CLICKHOUSE_PORT', 9000)),
        database=os.getenv('CLICKHOUSE_DATABASE', 'etl')
    )
    
    # Create bronze writer
    writer = BronzeWriter(client)
    
    # Create sample data
    sample_data = [
        {"id": "1", "name": "Alice", "email": "alice@example.com"},
        {"id": "2", "name": "Bob", "email": "bob@example.com"}
    ]
    
    # Write using direct method
    result = writer.write_rows_direct(
        table_name="bronze_demo",
        rows=sample_data,
        batch_id=f"demo_{uuid4()}",
        source_id="demo_source"
    )
    
    print(f"\nResult: {result}")
    print(f"Success: {result['success']}")
    print(f"Rows written: {result['rows_written']}")


if __name__ == "__main__":
    main()
