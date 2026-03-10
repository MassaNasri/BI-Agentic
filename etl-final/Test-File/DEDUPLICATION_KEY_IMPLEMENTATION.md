# Deduplication Key Implementation

## Overview

This document describes the implementation of deduplication key generation (SHA256 hash of row content) across the ETL pipeline services. This implementation fulfills Task 1.3.3 of the ETL Architecture Redesign specification.

## Design Principles

1. **Deterministic**: Same input always produces the same hash
2. **Order-Independent**: Different key order produces the same hash
3. **Collision-Resistant**: SHA256 provides strong collision resistance
4. **Lineage-Preserving**: Original and transformed hashes are both tracked

## Implementation Details

### IdempotencyManager

The `IdempotencyManager` class in `shared/utils/idempotency_manager.py` provides the core hash generation functionality:

```python
def generate_row_hash(self, row: Dict[str, Any]) -> str:
    """Generate SHA256 hash of row content for deduplication."""
    sorted_items = sorted(row.items())
    row_str = str(sorted_items)
    hash_obj = hashlib.sha256(row_str.encode('utf-8'))
    return hash_obj.hexdigest()
```

**Key Features:**
- Sorts dictionary keys for order-independence
- Uses SHA256 for cryptographic strength
- Returns 64-character hexadecimal string
- Stateless operation (no side effects)

### Extractor Service Integration

**File:** `extractor-service/extractor/engine/kafka_listener.py`

**Changes:**
1. Import `IdempotencyManager` and related classes
2. Initialize manager in `__init__` method
3. Generate batch_id for each extraction using `uuid4()`
4. Generate dedup key for each row using `generate_row_hash()`
5. Add metadata to extracted messages:
   - `_dedup_key`: SHA256 hash of row content
   - `batch_id`: Unique batch identifier
   - `_extracted_at`: Extraction timestamp


**Example Message Structure:**
```json
{
  "source": "users.csv",
  "batch_id": "550e8400-e29b-41d4-a716-446655440000",
  "row_id": 0,
  "data": {"id": 1, "name": "John Doe"},
  "_dedup_key": "abc123...",
  "_extracted_at": "2024-01-01T00:00:00"
}
```

### Transformer Service Integration

**File:** `transformer-service/transformer/engine/kafka_listener.py`

**Changes:**
1. Import `IdempotencyManager`
2. Initialize manager in `__init__` method
3. Preserve original dedup key from extractor
4. Generate new dedup key for transformed data
5. Add metadata to cleaned messages:
   - `_original_dedup_key`: Hash from extractor (for lineage)
   - `_transformed_dedup_key`: Hash of cleaned data
   - `_batch_id`: Preserved from extractor
   - `_extracted_at`: Preserved from extractor
   - `_cleaned_at`: Transformation timestamp

**Example Message Structure:**
```json
{
  "source": "users.csv",
  "data": {"id": 1, "name": "John Doe"},
  "_original_dedup_key": "abc123...",
  "_transformed_dedup_key": "def456...",
  "_batch_id": "550e8400-e29b-41d4-a716-446655440000",
  "_extracted_at": "2024-01-01T00:00:00",
  "_cleaned_at": "2024-01-01T00:00:01"
}
```

### Loader Service Integration

**File:** `loader-service/loader/engine/kafka_listener.py`

**Changes:**
1. Import `IdempotencyManager`
2. Initialize manager in `__init__` method
3. Preserve all dedup keys and metadata
4. Enrich row data with metadata columns for ClickHouse storage
5. Add `_loaded_at` timestamp


**Example Enriched Row:**
```json
{
  "id": 1,
  "name": "John Doe",
  "_original_dedup_key": "abc123...",
  "_transformed_dedup_key": "def456...",
  "_batch_id": "550e8400-e29b-41d4-a716-446655440000",
  "_extracted_at": "2024-01-01T00:00:00",
  "_cleaned_at": "2024-01-01T00:00:01",
  "_loaded_at": "2024-01-01T00:00:02"
}
```

## Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│ EXTRACTOR SERVICE                                           │
│ - Reads source data (file/database)                        │
│ - Generates batch_id (UUID)                                │
│ - Generates _dedup_key (SHA256 of row)                     │
│ - Adds _extracted_at timestamp                             │
└────────────────────┬────────────────────────────────────────┘
                     │ Kafka: extracted_rows_topic
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ TRANSFORMER SERVICE                                         │
│ - Applies cleaning rules                                   │
│ - Preserves _original_dedup_key                            │
│ - Generates _transformed_dedup_key                         │
│ - Adds _cleaned_at timestamp                               │
└────────────────────┬────────────────────────────────────────┘
                     │ Kafka: clean_rows_topic
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ LOADER SERVICE                                              │
│ - Preserves all dedup keys                                 │
│ - Enriches row with metadata                               │
│ - Adds _loaded_at timestamp                                │
│ - Stores in ClickHouse                                     │
└─────────────────────────────────────────────────────────────┘
```

## Testing

### Unit Tests

**File:** `shared/utils/test_idempotency_manager.py`
- Tests for hash generation (deterministic, order-independent)
- Tests for duplicate detection
- Tests for idempotent operations

### Integration Tests

**File:** `shared/utils/test_deduplication_integration.py`
- Tests for dedup key generation across services
- Tests for lineage preservation
- Tests for collision resistance
- End-to-end pipeline tests


**Running Tests:**
```bash
# Run IdempotencyManager tests
cd etl-final/shared/utils
python -m pytest test_idempotency_manager.py -v

# Run integration tests
python -m pytest test_deduplication_integration.py -v
```

**Test Results:**
- All 24 IdempotencyManager tests pass ✓
- All 18 integration tests pass ✓
- Total: 42 tests passing

## Benefits

1. **Idempotent Operations**: Same data processed multiple times produces same hash
2. **Duplicate Detection**: Can identify duplicate rows at any stage
3. **Data Lineage**: Track transformations from raw to cleaned data
4. **Collision-Free**: SHA256 provides strong collision resistance
5. **Order-Independent**: Hash is consistent regardless of key order
6. **Deterministic**: Same input always produces same output

## Future Enhancements

1. **ClickHouse Integration**: Use dedup keys with ReplacingMergeTree
2. **Duplicate Filtering**: Skip processing of duplicate rows
3. **Lineage Queries**: Query data lineage using dedup keys
4. **Quality Metrics**: Track duplicate rates per source
5. **Reprocessing**: Use dedup keys to identify rows for reprocessing

## Compliance with Requirements

This implementation satisfies:
- **FR-6**: Idempotent Operations - All operations have idempotency keys
- **US-1**: As a Data Engineer, I need idempotent ETL operations
- **AC 1.1**: Running the same extraction twice produces identical results
- **AC 1.2**: Transformation operations are deterministic and reproducible

## References

- Design Document: `.kiro/specs/etl-architecture-redesign/design.md`
- Requirements: `.kiro/specs/etl-architecture-redesign/requirements.md`
- Task List: `.kiro/specs/etl-architecture-redesign/tasks.md`
