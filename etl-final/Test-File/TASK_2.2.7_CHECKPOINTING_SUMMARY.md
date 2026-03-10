# Task 2.2.7: Extraction Checkpointing Implementation - Summary

## Task Overview

**Task**: 2.2.7 Implement extraction checkpointing for resume capability  
**Phase**: Phase 2: Bronze Layer Implementation  
**Status**: ✅ COMPLETED

## Objective

Implement a checkpointing mechanism that saves extraction state after each batch, enabling failed extractions to resume from the last successful point instead of starting over.

## Requirements Addressed

- **US-1**: Idempotent ETL operations (AC 1.3: Failed operations can be safely retried without data corruption)
- **NFR-3**: Reliability - Automatic retry with exponential backoff
- **Section 3.2**: Extractor Service (Redesigned) - Add extraction checkpointing
- **Section 5.2**: Loader Service Enhancement - Implement retry logic with exponential backoff

## Implementation Summary

### 1. Core Components Created

#### ExtractionCheckpoint Data Class
- Stores checkpoint state (extraction_id, source_id, last_offset, last_batch_id, timestamp)
- Supports multiple statuses: ACTIVE, COMPLETED, FAILED, RESUMED
- Includes metadata for distributed tracing (correlation_id)
- Serializable to/from dictionary for persistence

#### CheckpointManager Class
- Manages checkpoint lifecycle (create, update, complete, fail)
- Persists checkpoints to ClickHouse using ReplacingMergeTree
- Provides resume capability with `can_resume()` and `resume_from_checkpoint()`
- Includes cleanup logic for old completed checkpoints
- Falls back to in-memory storage if ClickHouse unavailable

### 2. ClickHouse Schema

```sql
CREATE TABLE extraction_checkpoints (
    extraction_id String,
    source_id String,
    source_type String,
    last_offset UInt64,
    last_batch_id String,
    rows_extracted UInt64,
    batches_processed UInt32,
    status String,
    created_at DateTime64(3),
    updated_at DateTime64(3),
    completed_at Nullable(DateTime64(3)),
    error_message Nullable(String),
    correlation_id Nullable(String),
    metadata String
) ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(created_at)
ORDER BY (extraction_id, updated_at);
```

### 3. Key Features

#### Resume Capability
- Failed extractions can resume from last successful offset
- Prevents re-extraction of already processed data
- Supports both CSV and database extraction strategies

#### Idempotency
- Deterministic batch IDs ensure same offset produces same batch
- Checkpoint state persists across service restarts
- Safe retry mechanism for failed operations

#### Integration with Progress Tracking
- Works seamlessly with progress tracking (task 2.2.6)
- Checkpoint stores persistent state for resume
- Progress tracks ephemeral metrics for monitoring

#### Cleanup
- Automatic cleanup of old completed checkpoints
- Configurable retention period (default: 7 days)
- Keeps failed checkpoints for debugging

### 4. Files Created

1. **extraction_checkpoint.py** (620 lines)
   - ExtractionCheckpoint data class
   - CheckpointManager implementation
   - ClickHouse persistence logic
   - Resume and cleanup functionality

2. **test_extraction_checkpoint.py** (550 lines)
   - 25 unit tests covering all checkpoint operations
   - Tests for checkpoint creation, updates, completion, failure
   - Tests for resume capability and idempotency
   - Tests for in-memory and ClickHouse modes

3. **test_checkpoint_integration.py** (480 lines)
   - 5 integration tests with extraction strategies
   - CSV extraction with checkpointing
   - Database extraction with checkpointing
   - Resume after failure scenarios
   - Idempotency verification

4. **EXTRACTION_CHECKPOINTING.md** (comprehensive documentation)
   - Architecture overview
   - Usage examples
   - Integration guide
   - Best practices
   - Monitoring and observability

## Test Results

### Unit Tests
```
test_extraction_checkpoint.py::TestExtractionCheckpoint::test_checkpoint_creation PASSED
test_extraction_checkpoint.py::TestExtractionCheckpoint::test_checkpoint_to_dict PASSED
test_extraction_checkpoint.py::TestExtractionCheckpoint::test_checkpoint_from_dict PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_create_checkpoint PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_create_checkpoint_persists_to_clickhouse PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_update_checkpoint PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_update_checkpoint_incremental PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_update_nonexistent_checkpoint PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_complete_checkpoint PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_fail_checkpoint PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_get_checkpoint PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_get_nonexistent_checkpoint PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_can_resume_active_checkpoint PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_can_resume_failed_checkpoint PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_cannot_resume_completed_checkpoint PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_cannot_resume_zero_offset PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_resume_from_checkpoint PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_resume_from_failed_checkpoint PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_cannot_resume_nonexistent_checkpoint PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_list_active_checkpoints PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_in_memory_only_mode PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_cleanup_old_checkpoints PASSED
test_extraction_checkpoint.py::TestCheckpointManager::test_checkpoint_idempotency PASSED
test_extraction_checkpoint.py::TestCheckpointIntegration::test_checkpoint_with_csv_extraction PASSED
test_extraction_checkpoint.py::TestCheckpointIntegration::test_checkpoint_resume_after_failure PASSED

=================== 25 passed in 1.24s ===================
```

### Integration Tests
```
test_checkpoint_integration.py::TestCheckpointWithCSVExtraction::test_csv_extraction_with_checkpointing PASSED
test_checkpoint_integration.py::TestCheckpointWithCSVExtraction::test_csv_extraction_resume_after_failure PASSED
test_checkpoint_integration.py::TestCheckpointWithDatabaseExtraction::test_database_extraction_with_checkpointing PASSED
test_checkpoint_integration.py::TestCheckpointWithDatabaseExtraction::test_database_extraction_resume_after_failure PASSED
test_checkpoint_integration.py::TestCheckpointIdempotency::test_checkpoint_prevents_duplicate_extraction PASSED

=================== 5 passed in 3.17s ===================
```

**Total: 30 tests, 100% passing**

## Usage Example

### Basic Extraction with Checkpointing

```python
from extraction_checkpoint import CheckpointManager
from extraction_progress import ProgressTracker
from csv_extraction_strategy import CSVExtractionStrategy
from extraction_strategy import ExtractionConfig

# Initialize managers
checkpoint_manager = CheckpointManager(clickhouse_client=client)
progress_tracker = ProgressTracker(metadata_client=metadata_client)

# Create extraction config
extraction_id = "ext_csv_123"
config = ExtractionConfig(
    source_id="customers_csv",
    source_type="csv",
    connection_params={"file_path": "/data/customers.csv"},
    batch_size=1000,
    extraction_id=extraction_id,
    progress_tracker=progress_tracker
)

# Create checkpoint
checkpoint_manager.create_checkpoint(
    extraction_id=extraction_id,
    source_id="customers_csv",
    source_type="csv"
)

# Extract data in batches
strategy = CSVExtractionStrategy()
offset = 0

try:
    while True:
        batch = strategy.extract_batch(config, offset, config.batch_size)
        
        # Process batch (write to bronze layer)
        # ... bronze_writer.write_batch(batch) ...
        
        # Update checkpoint after successful batch
        checkpoint_manager.update_checkpoint(
            extraction_id=extraction_id,
            last_offset=offset + batch.total_rows,
            last_batch_id=batch.batch_id,
            rows_extracted=offset + batch.total_rows,
            batches_processed=(offset // config.batch_size) + 1
        )
        
        if not batch.has_more:
            break
        offset += batch.total_rows
    
    # Complete checkpoint
    checkpoint_manager.complete_checkpoint(extraction_id=extraction_id)

except Exception as e:
    # Fail checkpoint on error
    checkpoint_manager.fail_checkpoint(extraction_id=extraction_id, error_message=str(e))
    raise
```

### Resuming from Checkpoint

```python
# Check if extraction can be resumed
if checkpoint_manager.can_resume(extraction_id):
    # Resume from checkpoint
    checkpoint = checkpoint_manager.resume_from_checkpoint(extraction_id)
    
    # Continue from last offset
    offset = checkpoint.last_offset
    total_rows = checkpoint.rows_extracted
    
    # Continue extraction loop...
```

## Key Benefits

1. **Reliability**: Failed extractions can resume without data loss
2. **Efficiency**: No need to re-extract already processed data
3. **Idempotency**: Safe retry mechanism for failed operations
4. **Observability**: Checkpoint status queryable for monitoring
5. **Persistence**: Survives service restarts via ClickHouse storage
6. **Integration**: Works seamlessly with progress tracking

## Design Decisions

### Why ReplacingMergeTree?
- Efficient updates without explicit DELETE operations
- Automatically keeps latest version based on updated_at
- Optimized for frequent checkpoint updates

### Why In-Memory Cache?
- Reduces ClickHouse queries during active extractions
- Fast access to checkpoint state
- Falls back to ClickHouse if not in cache

### Why Offset-Based Resume?
- Simple and deterministic
- Works with both CSV and database extraction
- Prevents duplicate data extraction

### Why Separate from Progress Tracking?
- Checkpoint: Persistent state for resume (long-lived)
- Progress: Ephemeral metrics for monitoring (short-lived)
- Different use cases, different lifetimes

## Performance Characteristics

- **Checkpoint Update**: O(1) - in-memory update + async ClickHouse write
- **Checkpoint Lookup**: O(1) - in-memory cache or ClickHouse index
- **Resume Check**: O(1) - simple status and offset check
- **Cleanup**: O(partitions) - efficient partition-level deletion

## Monitoring

### Metrics to Track
- Active checkpoints count
- Failed checkpoints count
- Resume rate (% of extractions resumed)
- Checkpoint update latency

### Queries for Monitoring

```sql
-- Active extractions
SELECT extraction_id, source_id, rows_extracted, updated_at
FROM extraction_checkpoints
WHERE status = 'active'
ORDER BY updated_at DESC;

-- Failed extractions
SELECT extraction_id, source_id, error_message, updated_at
FROM extraction_checkpoints
WHERE status = 'failed'
ORDER BY updated_at DESC;
```

## Integration Points

1. **Extraction Strategies**: Checkpoints updated after each batch
2. **Progress Tracking**: Parallel tracking for monitoring
3. **Bronze Writer**: Checkpoint updated after successful write
4. **Error Handling**: Checkpoint marked as FAILED on errors
5. **Retry Logic**: Resume from checkpoint on retry

## Future Enhancements

1. **Automatic Resume**: Auto-resume failed extractions on service restart
2. **Checkpoint Compression**: Compress metadata for large extractions
3. **Multi-Level Checkpoints**: File-level and batch-level checkpoints
4. **Checkpoint Validation**: Validate integrity before resume
5. **Checkpoint Replication**: Replicate across ClickHouse nodes

## Conclusion

Task 2.2.7 successfully implements extraction checkpointing with:
- ✅ Checkpoint creation and updates after each batch
- ✅ Resume capability for failed extractions
- ✅ Persistent storage in ClickHouse
- ✅ Cleanup logic for old checkpoints
- ✅ Integration with progress tracking
- ✅ Comprehensive test coverage (30 tests, 100% passing)
- ✅ Complete documentation

The implementation provides a robust foundation for reliable, resumable extractions that can recover from failures without data loss or duplication.

## Related Tasks

- **Task 2.2.6**: Extraction progress tracking (integrated with checkpointing)
- **Task 2.2.5**: Bronze layer write implementation (checkpoint after write)
- **Task 2.2.4**: Batch ID and source ID generation (used in checkpoints)
- **Task 2.1.1**: Bronze schema design (checkpoint table schema)

## Documentation

- [EXTRACTION_CHECKPOINTING.md](./extractor-service/EXTRACTION_CHECKPOINTING.md) - Comprehensive guide
- [extraction_checkpoint.py](./extractor-service/extractor/engine/extraction_checkpoint.py) - Implementation
- [test_extraction_checkpoint.py](./extractor-service/extractor/engine/test_extraction_checkpoint.py) - Unit tests
- [test_checkpoint_integration.py](./extractor-service/extractor/engine/test_checkpoint_integration.py) - Integration tests
