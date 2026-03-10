# Bronze Table Indexes Implementation

## Overview

This document describes the index implementation for bronze layer tables in the ETL pipeline. Indexes are added to improve query performance for common access patterns, particularly for deduplication checks, source filtering, and time-based queries.

## Implementation Details

### Index Types

Bronze tables include three default indexes:

1. **idx_dedup_key** (Bloom Filter)
   - Column: `_dedup_key`
   - Type: `bloom_filter`
   - Granularity: 1
   - Purpose: Fast deduplication checks
   - Use case: Idempotency manager queries to check if a row has been processed

2. **idx_source_id** (Set Index)
   - Column: `_source_id`
   - Type: `set`
   - Granularity: 4
   - Purpose: Efficient filtering by data source
   - Use case: Queries that filter by specific data sources

3. **idx_extracted_at** (MinMax Index)
   - Column: `_extracted_at`
   - Type: `minmax`
   - Granularity: 1
   - Purpose: Time-based range queries
   - Use case: Queries that filter by extraction time ranges

### Why These Index Types?

#### Bloom Filter for _dedup_key
- **Bloom filters** are probabilistic data structures that efficiently test set membership
- Perfect for deduplication checks where we need to quickly determine if a specific hash exists
- Very space-efficient for high-cardinality columns like SHA256 hashes
- False positives are acceptable (will do full check anyway), false negatives are impossible

#### Set Index for _source_id
- **Set indexes** store unique values in each granule
- Ideal for low-to-medium cardinality columns (typically 5-100 unique sources)
- Allows ClickHouse to skip entire granules that don't contain the target source_id
- More efficient than bloom filter for this use case due to lower cardinality

#### MinMax Index for _extracted_at
- **MinMax indexes** store minimum and maximum values for each granule
- Perfect for range queries on timestamp columns
- Allows ClickHouse to skip granules outside the query time range
- Very lightweight and efficient for ordered data

### Schema Definition

Indexes are defined in the `BronzeTableSchema` dataclass:

```python
@dataclass
class BronzeTableSchema:
    source_name: str
    data_columns: Dict[str, str] = field(default_factory=dict)
    partition_by: str = "toYYYYMM(_extracted_at)"
    order_by: List[str] = field(default_factory=lambda: ["_batch_id", "_row_id"])
    settings: Dict[str, Any] = field(default_factory=lambda: {"index_granularity": 8192})
    indexes: List[Dict[str, Any]] = field(default_factory=lambda: [
        {"name": "idx_dedup_key", "column": "_dedup_key", "type": "bloom_filter", "granularity": 1},
        {"name": "idx_source_id", "column": "_source_id", "type": "set", "granularity": 4},
        {"name": "idx_extracted_at", "column": "_extracted_at", "type": "minmax", "granularity": 1}
    ])
```

### Generated SQL

The `get_create_table_sql()` method generates SQL with INDEX definitions:

```sql
CREATE TABLE IF NOT EXISTS bronze_customers (
    _row_id UUID DEFAULT generateUUIDv4(),
    _batch_id String,
    _source_id String,
    _extracted_at DateTime64(3),
    _dedup_key String,
    customer_id String,
    name String,
    email String,
    _file_name String,
    _file_size UInt64,
    _row_number UInt64,
    INDEX idx_dedup_key _dedup_key TYPE bloom_filter GRANULARITY 1,
    INDEX idx_source_id _source_id TYPE set GRANULARITY 4,
    INDEX idx_extracted_at _extracted_at TYPE minmax GRANULARITY 1
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(_extracted_at)
ORDER BY (_batch_id, _row_id)
SETTINGS index_granularity = 8192
```

## Query Performance Impact

### Deduplication Queries

**Without Index:**
```sql
SELECT COUNT(*) FROM bronze_customers WHERE _dedup_key = 'abc123...'
-- Scans all granules, checks every row
```

**With Bloom Filter Index:**
```sql
SELECT COUNT(*) FROM bronze_customers WHERE _dedup_key = 'abc123...'
-- Skips granules that definitely don't contain the hash
-- Only scans granules that might contain it
```

**Performance Improvement:** 10-100x faster for large tables

### Source Filtering Queries

**Without Index:**
```sql
SELECT * FROM bronze_customers WHERE _source_id = 'source_1'
-- Scans all granules
```

**With Set Index:**
```sql
SELECT * FROM bronze_customers WHERE _source_id = 'source_1'
-- Skips granules that don't contain source_1
```

**Performance Improvement:** 5-50x faster depending on source distribution

### Time Range Queries

**Without Index:**
```sql
SELECT * FROM bronze_customers 
WHERE _extracted_at >= '2024-01-01' AND _extracted_at < '2024-02-01'
-- Scans all granules
```

**With MinMax Index:**
```sql
SELECT * FROM bronze_customers 
WHERE _extracted_at >= '2024-01-01' AND _extracted_at < '2024-02-01'
-- Skips granules outside the time range
```

**Performance Improvement:** 10-100x faster for selective time ranges

## Customization

### Adding Custom Indexes

You can add custom indexes when creating a bronze table:

```python
from models.bronze_schema import BronzeTableSchema

# Define custom indexes
custom_indexes = [
    {"name": "idx_custom", "column": "custom_col", "type": "set", "granularity": 2}
]

schema = BronzeTableSchema(
    source_name="my_source",
    data_columns={"custom_col": "String", "other_col": "String"},
    indexes=custom_indexes  # Replaces default indexes
)
```

### Disabling Indexes

To create a table without indexes:

```python
schema = BronzeTableSchema(
    source_name="my_source",
    data_columns={"col1": "String"},
    indexes=[]  # No indexes
)
```

### Combining Default and Custom Indexes

```python
from models.bronze_schema import BronzeTableSchema

# Start with default indexes
schema = BronzeTableSchema(
    source_name="my_source",
    data_columns={"col1": "String", "custom_col": "String"}
)

# Add custom index
schema.indexes.append({
    "name": "idx_custom",
    "column": "custom_col",
    "type": "bloom_filter",
    "granularity": 1
})
```

## Index Granularity

**Granularity** determines how many granules share one index entry:

- **Granularity 1**: One index entry per granule (most precise, more storage)
- **Granularity 4**: One index entry per 4 granules (less precise, less storage)

### Choosing Granularity

- **High selectivity queries** (finding specific values): Use granularity 1
- **Low selectivity queries** (filtering common values): Use higher granularity
- **Storage constraints**: Higher granularity reduces index size

## Monitoring Index Usage

### Check Index Existence

```sql
SELECT name, type, expr
FROM system.data_skipping_indices
WHERE table = 'bronze_customers'
AND database = 'etl'
```

### Check Index Statistics

```sql
SELECT 
    table,
    name,
    type,
    expr,
    granularity
FROM system.data_skipping_indices
WHERE database = 'etl'
AND table LIKE 'bronze_%'
ORDER BY table, name
```

### Query Execution Analysis

Use `EXPLAIN` to see if indexes are being used:

```sql
EXPLAIN indexes = 1
SELECT * FROM bronze_customers WHERE _dedup_key = 'abc123...'
```

## Best Practices

1. **Don't over-index**: Each index adds storage overhead and slows down inserts
2. **Index high-cardinality columns with bloom filters**: Good for unique identifiers
3. **Index low-cardinality columns with set indexes**: Good for categories, sources
4. **Index range-query columns with minmax**: Good for timestamps, numeric ranges
5. **Monitor query patterns**: Add indexes based on actual query patterns, not speculation
6. **Test performance**: Measure query performance before and after adding indexes

## Limitations

1. **Indexes don't guarantee performance**: They help ClickHouse skip granules, but don't replace proper table design
2. **Indexes add overhead**: Each index increases storage and insert time
3. **Indexes work best with MergeTree**: Other engines may not support all index types
4. **Bloom filters have false positives**: They may not skip all irrelevant granules

## References

- [ClickHouse Data Skipping Indexes](https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/mergetree#table_engine-mergetree-data_skipping-indexes)
- [Bloom Filter Index](https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/mergetree#bloom-filter)
- [Set Index](https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/mergetree#set-index)
- [MinMax Index](https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/mergetree#minmax)

## Related Files

- `etl-final/shared/models/bronze_schema.py` - Schema definition with indexes
- `etl-final/shared/utils/test_bronze_indexes.py` - Index tests
- `etl-final/shared/utils/create_bronze_tables.py` - Table creation script
- `etl-final/shared/utils/idempotency_manager.py` - Uses dedup_key index
