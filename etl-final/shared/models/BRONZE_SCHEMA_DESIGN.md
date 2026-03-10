# Bronze Layer Schema Design

**Task:** 2.1.1 - Design bronze table schema with lineage columns  
**Status:** Complete  
**Date:** 2024-02-17

## Overview

The bronze layer implements immutable raw data storage with comprehensive lineage tracking as part of the Medallion Architecture. This design satisfies:

- **FR-1:** Immutable Raw Layer - All extracted data stored with `_extracted_at`, `_source_id`, `_batch_id`
- **US-2:** As a Data Engineer, I need immutable raw data storage

## Architecture

### Design Principles

1. **Immutability First:** Raw data is never modified after insertion
2. **Complete Lineage:** Every row tracks its origin and extraction metadata
3. **Deduplication Support:** SHA256 hash enables idempotent operations
4. **Type Preservation:** All data columns stored as String initially to preserve original format
5. **Queryability:** Partitioned and indexed for efficient querying

### Schema Components

#### 1. Lineage Columns (Always Present)

| Column | Type | Purpose |
|--------|------|---------|
| `_row_id` | UUID | Unique identifier for each row (auto-generated) |
| `_batch_id` | String | Identifies the extraction batch |
| `_source_id` | String | Identifies the data source |
| `_extracted_at` | DateTime64(3) | Timestamp when data was extracted (millisecond precision) |
| `_dedup_key` | String | SHA256 hash for deduplication (based on source_id + batch_id + data) |

#### 2. Data Columns (Variable)

All data columns are initially stored as `String` type to:
- Preserve original format (e.g., leading zeros in "007")
- Avoid type coercion errors during extraction
- Enable flexible schema evolution
- Support later type inference in Silver layer

#### 3. Metadata Columns (Always Present)

| Column | Type | Purpose |
|--------|------|---------|
| `_file_name` | String | Name of source file (if applicable) |
| `_file_size` | UInt64 | Size of source file in bytes |
| `_row_number` | UInt64 | Row number in source file/table |

### Table Engine Configuration

```sql
ENGINE = MergeTree()
PARTITION BY toYYYYMM(_extracted_at)
ORDER BY (_batch_id, _row_id)
SETTINGS index_granularity = 8192
```

**Rationale:**
- **MergeTree:** Efficient for analytical queries and large datasets
- **Monthly Partitioning:** Balances query performance with partition management
- **Ordering:** Enables efficient batch-level queries and row lookups
- **Index Granularity:** Default ClickHouse setting for optimal performance

## Implementation

### Python Data Models

#### BronzeTableSchema

Defines the structure of a bronze table:

```python
schema = BronzeTableSchema(
    source_name="customers",
    data_columns={"id": "String", "name": "String", "email": "String"}
)

# Generate CREATE TABLE SQL
sql = schema.get_create_table_sql()
```

#### BronzeRow

Represents a single row with automatic deduplication key generation:

```python
row = BronzeRow(
    batch_id="batch_001",
    source_id="customers",
    extracted_at=datetime.now(),
    data={"id": "1", "name": "John Doe", "email": "john@example.com"},
    file_name="customers.csv",
    file_size=1024,
    row_number=1
)

# Dedup key is auto-generated
assert len(row.dedup_key) == 64  # SHA256 hash

# Validate row
is_valid, errors = row.validate()

# Convert to dict for ClickHouse insertion
row_dict = row.to_dict()
```

#### BronzeBatch

Manages batch operations:

```python
batch = BronzeBatch(
    batch_id="batch_001",
    source_id="customers",
    rows=[row1, row2, row3],
    schema=schema
)

# Validate entire batch
is_valid, errors = batch.validate()

# Convert to list of dicts for bulk insert
dicts = batch.to_dicts()

# Get all dedup keys for duplicate checking
dedup_keys = batch.get_dedup_keys()
```

### Deduplication Key Generation

The deduplication key is a SHA256 hash of:
- `source_id`: Identifies the data source
- `batch_id`: Identifies the extraction batch
- `data`: The actual row content (JSON serialized with sorted keys)

This ensures:
- **Deterministic:** Same data always produces same hash
- **Unique:** Different data produces different hashes
- **Idempotent:** Re-extracting same data is detected

```python
def generate_dedup_key(self) -> str:
    key_components = {
        "source_id": self.source_id,
        "batch_id": self.batch_id,
        "data": self.data
    }
    key_json = json.dumps(key_components, sort_keys=True)
    return hashlib.sha256(key_json.encode('utf-8')).hexdigest()
```

## Usage Examples

### Creating a Bronze Table

```python
from clickhouse_driver import Client
from clickhouse_schemas import ClickHouseSchemaManager
from models.bronze_schema import BronzeTableSchema

# Connect to ClickHouse
client = Client(host='localhost', port=9000, database='etl')
schema_manager = ClickHouseSchemaManager(client)

# Define schema
schema = BronzeTableSchema(
    source_name="orders",
    data_columns={
        "order_id": "String",
        "customer_id": "String",
        "amount": "String",
        "order_date": "String"
    }
)

# Create table
schema_manager.create_bronze_table(schema)
```

### Inserting Data

```python
from datetime import datetime
from models.bronze_schema import BronzeRow, BronzeBatch

# Create rows
rows = [
    BronzeRow(
        batch_id="batch_001",
        source_id="orders",
        extracted_at=datetime.now(),
        data={"order_id": "1", "customer_id": "100", "amount": "99.99", "order_date": "2024-01-15"},
        file_name="orders.csv",
        file_size=2048,
        row_number=1
    ),
    BronzeRow(
        batch_id="batch_001",
        source_id="orders",
        extracted_at=datetime.now(),
        data={"order_id": "2", "customer_id": "101", "amount": "149.99", "order_date": "2024-01-15"},
        file_name="orders.csv",
        file_size=2048,
        row_number=2
    )
]

# Create batch
batch = BronzeBatch(
    batch_id="batch_001",
    source_id="orders",
    rows=rows,
    schema=schema
)

# Validate
is_valid, errors = batch.validate()
if not is_valid:
    print(f"Validation errors: {errors}")
else:
    # Insert into ClickHouse
    client.execute(
        f"INSERT INTO {schema.table_name} VALUES",
        batch.to_dicts()
    )
```

### Querying Bronze Data

```sql
-- Get all data for a specific batch
SELECT * FROM bronze_orders
WHERE _batch_id = 'batch_001'
ORDER BY _row_number;

-- Get data extracted in a specific time range
SELECT * FROM bronze_orders
WHERE _extracted_at >= '2024-01-01' AND _extracted_at < '2024-02-01';

-- Check for duplicates using dedup_key
SELECT _dedup_key, COUNT(*) as count
FROM bronze_orders
GROUP BY _dedup_key
HAVING count > 1;

-- Trace lineage for a specific row
SELECT _row_id, _batch_id, _source_id, _extracted_at, _file_name
FROM bronze_orders
WHERE _row_id = 'some-uuid-here';
```

## Testing

Comprehensive unit tests cover:

1. **Schema Generation:** Table name, SQL structure, partitioning, ordering
2. **Row Operations:** Creation, validation, dedup key generation, dict conversion
3. **Batch Operations:** Validation, consistency checks, bulk operations
4. **Deduplication:** Deterministic hashing, uniqueness verification
5. **Integration:** ClickHouse table creation, data insertion, querying

Run tests:
```bash
pytest etl-final/shared/models/test_bronze_schema.py -v
```

## Benefits

### For Data Engineers

- **Idempotent Operations:** Safe to re-run extractions without duplicates
- **Complete Audit Trail:** Every row traceable to source and extraction time
- **Flexible Schema Evolution:** String storage allows later type refinement
- **Efficient Queries:** Partitioning and indexing optimize performance

### For Data Quality

- **Immutable History:** Original data never lost or modified
- **Deduplication Support:** Automatic detection of duplicate extractions
- **Validation Framework:** Built-in validation before insertion
- **Batch Consistency:** Ensures all rows in batch have consistent metadata

### For Operations

- **Observability:** Lineage columns enable debugging and monitoring
- **Scalability:** Partitioning supports large datasets
- **Maintainability:** Declarative schema definitions
- **Testability:** Pure functions with comprehensive test coverage

## Next Steps

This bronze schema design enables:

1. **Task 2.1.2:** Create bronze table creation scripts
2. **Task 2.2:** Extractor service redesign to write to bronze tables
3. **Task 2.4:** Integration tests for bronze layer writes
4. **Phase 3:** Silver layer implementation with type-aware transformations

## References

- **Requirements:** `.kiro/specs/etl-architecture-redesign/requirements.md`
- **Design:** `.kiro/specs/etl-architecture-redesign/design.md` (Section 5.1)
- **Implementation:** `etl-final/shared/models/bronze_schema.py`
- **Tests:** `etl-final/shared/models/test_bronze_schema.py`
