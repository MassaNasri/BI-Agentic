# Bronze Table Creation Scripts

This directory contains scripts for creating bronze layer tables in ClickHouse as part of the ETL architecture redesign.

## Overview

The bronze layer stores **immutable raw data** with comprehensive lineage tracking, implementing:
- **FR-1**: Immutable Raw Layer
- **US-2**: As a Data Engineer, I need immutable raw data storage

## Components

### 1. `create_bronze_tables.py`
Main script for creating bronze tables. Can be used as:
- **Standalone CLI tool**: Create tables from command line
- **Python module**: Import and use programmatically

### 2. `bronze_tables_config.example.json`
Example configuration file showing how to define multiple tables at once.

### 3. `test_create_bronze_tables.py`
Comprehensive test suite with unit tests and integration tests.

## Usage

### Prerequisites

Set up ClickHouse connection via environment variables:

```bash
export CLICKHOUSE_HOST=localhost
export CLICKHOUSE_PORT=9000
export CLICKHOUSE_USER=default
export CLICKHOUSE_PASSWORD=your_password
export CLICKHOUSE_DATABASE=etl
```

### Command Line Usage

#### Create a Single Table

```bash
python create_bronze_tables.py --source customers --columns id,name,email,phone
```

This creates a table named `bronze_customers` with:
- **Lineage columns**: `_row_id`, `_batch_id`, `_source_id`, `_extracted_at`, `_dedup_key`
- **Data columns**: `id`, `name`, `email`, `phone` (all as String type)
- **Metadata columns**: `_file_name`, `_file_size`, `_row_number`

#### Create with Custom Partitioning

```bash
python create_bronze_tables.py \
  --source events \
  --columns event_id,event_type,timestamp \
  --partition-by "toYYYYMMDD(_extracted_at)"
```

#### Create with Custom Ordering

```bash
python create_bronze_tables.py \
  --source logs \
  --columns log_id,level,message \
  --order-by "_extracted_at,_row_id"
```

#### Create Multiple Tables from Config

```bash
python create_bronze_tables.py --config bronze_tables_config.json
```

Example config file:
```json
{
  "tables": [
    {
      "source_name": "customers",
      "columns": ["customer_id", "name", "email"]
    },
    {
      "source_name": "orders",
      "columns": ["order_id", "customer_id", "amount"],
      "partition_by": "toYYYYMMDD(_extracted_at)"
    }
  ]
}
```

#### Check if Table Exists

```bash
python create_bronze_tables.py --check customers
```

### Programmatic Usage

```python
from create_bronze_tables import BronzeTableCreator

# Initialize creator (uses environment variables)
creator = BronzeTableCreator()

# Create a single table
creator.create_table(
    source_name="customers",
    columns=["id", "name", "email"]
)

# Create with custom settings
creator.create_table(
    source_name="events",
    columns=["event_id", "event_type", "timestamp"],
    partition_by="toYYYYMMDD(_extracted_at)",
    order_by=["_extracted_at", "_row_id"],
    settings={"index_granularity": 4096}
)

# Create from schema object
from models.bronze_schema import BronzeTableSchema

schema = BronzeTableSchema(
    source_name="orders",
    data_columns={"order_id": "String", "amount": "String"}
)
creator.create_table_from_schema(schema)

# Create multiple tables
table_definitions = [
    {"source_name": "customers", "columns": ["id", "name"]},
    {"source_name": "orders", "columns": ["order_id", "customer_id"]}
]
results = creator.create_multiple_tables(table_definitions)

# Check if table exists
if creator.table_exists("customers"):
    schema = creator.get_table_schema("customers")
    print(f"Table has {len(schema)} columns")
```

### Using with Custom ClickHouse Client

```python
from clickhouse_driver import Client
from create_bronze_tables import BronzeTableCreator

# Create custom client
client = Client(
    host='my-clickhouse-server',
    port=9000,
    user='etl_user',
    password='secret',
    database='production_etl'
)

# Initialize creator with custom client
creator = BronzeTableCreator(client=client)

# Use as normal
creator.create_table("customers", ["id", "name", "email"])
```

## Bronze Table Schema

All bronze tables follow this structure:

### Lineage Columns (Always Present)
- `_row_id`: UUID - Unique identifier for each row
- `_batch_id`: String - Batch identifier for extraction
- `_source_id`: String - Data source identifier
- `_extracted_at`: DateTime64(3) - Extraction timestamp
- `_dedup_key`: String - SHA256 hash for deduplication

### Data Columns (User-Defined)
- All data columns are initially stored as **String** type
- Preserves original format from source
- Type conversion happens in silver layer

### Metadata Columns (Always Present)
- `_file_name`: String - Source file name (if applicable)
- `_file_size`: UInt64 - Source file size in bytes
- `_row_number`: UInt64 - Row number in source

### Table Engine
- **Engine**: MergeTree
- **Partition**: Monthly by `_extracted_at` (default: `toYYYYMM(_extracted_at)`)
- **Order**: `_batch_id`, `_row_id` (default)
- **Settings**: `index_granularity = 8192` (default)

## Testing

### Run Unit Tests

```bash
python -m pytest etl-final/shared/utils/test_create_bronze_tables.py::TestBronzeTableCreator -v
```

### Run Integration Tests

Integration tests require a running ClickHouse instance:

```bash
python -m pytest etl-final/shared/utils/test_create_bronze_tables.py::TestBronzeTableCreatorIntegration -v
```

### Run All Tests

```bash
python -m pytest etl-final/shared/utils/test_create_bronze_tables.py -v
```

## Error Handling

The script includes comprehensive error handling:

1. **Connection Errors**: Fails gracefully if ClickHouse is unavailable
2. **Validation Errors**: Checks for empty source names and column lists
3. **Database Errors**: Logs ClickHouse errors with full traceback
4. **Idempotency**: Creating the same table multiple times is safe (uses `CREATE TABLE IF NOT EXISTS`)

## Logging

The script uses Python's logging module with INFO level by default:

```
2024-01-15 10:30:00 - create_bronze_tables - INFO - Connecting to ClickHouse at localhost:9000/etl
2024-01-15 10:30:01 - create_bronze_tables - INFO - Creating bronze table for source 'customers' with 3 columns
2024-01-15 10:30:01 - create_bronze_tables - INFO - ✓ Bronze table 'bronze_customers' created successfully
```

## Integration with ETL Pipeline

The bronze table creation scripts integrate with:

1. **BronzeTableSchema** (`etl-final/shared/models/bronze_schema.py`):
   - Defines table structure
   - Generates CREATE TABLE SQL
   - Validates schema definitions

2. **ClickHouseSchemaManager** (`etl-final/shared/utils/clickhouse_schemas.py`):
   - Manages ClickHouse connections
   - Creates tables
   - Checks table existence
   - Retrieves table schemas

3. **Extractor Service**:
   - Uses bronze tables to store raw extracted data
   - Populates lineage columns during extraction
   - Ensures idempotent writes via deduplication

## Best Practices

1. **Always use String type initially**: Bronze layer preserves original format
2. **Use monthly partitioning**: Default `toYYYYMM(_extracted_at)` works for most cases
3. **Keep default ordering**: `_batch_id`, `_row_id` enables efficient queries
4. **Create tables before extraction**: Ensure tables exist before starting ETL jobs
5. **Use config files for multiple tables**: Easier to manage and version control
6. **Test with integration tests**: Verify tables work with actual ClickHouse

## Troubleshooting

### Table Creation Fails

```bash
# Check ClickHouse connection
python -c "from clickhouse_driver import Client; Client(host='localhost').execute('SELECT 1')"

# Verify environment variables
echo $CLICKHOUSE_HOST
echo $CLICKHOUSE_DATABASE

# Check if database exists
python create_bronze_tables.py --check customers
```

### Import Errors

Ensure you're running from the correct directory:

```bash
cd etl-final/shared/utils
python create_bronze_tables.py --help
```

### Permission Errors

Ensure your ClickHouse user has CREATE TABLE permissions:

```sql
GRANT CREATE TABLE ON etl.* TO your_user;
```

## Related Documentation

- **Bronze Schema Design**: `etl-final/shared/models/BRONZE_SCHEMA_DESIGN.md`
- **ClickHouse Schemas**: `etl-final/shared/utils/clickhouse_schemas.py`
- **ETL Architecture Spec**: `.kiro/specs/etl-architecture-redesign/design.md`

## Support

For issues or questions:
1. Check the test suite for usage examples
2. Review the design document for architecture details
3. Examine existing bronze tables in ClickHouse
