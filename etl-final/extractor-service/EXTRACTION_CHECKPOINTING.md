# Extraction Checkpointing Implementation

## Overview

This document describes the extraction checkpointing implementation for the ETL pipeline. Checkpointing enables failed extractions to resume from the last successful point instead of starting over, improving reliability and efficiency.

## Requirements Addressed

- **US-1**: Idempotent ETL operations (AC 1.3: Failed operations can be safely retried without data corruption)
- **NFR-3**: Reliability - Automatic retry with exponential backoff
- **Section 3.2**: Extractor Service (Redesigned) - Add extraction checkpointing
- **Section 5.2**: Loader Service Enhancement - Implement retry logic with exponential backoff

## Architecture

### Components

1. **ExtractionCheckpoint**: Data class representing a checkpoint
2. **CheckpointManager**: Manages checkpoint lifecycle and persistence
3. **Integration with ExtractionStrategy**: Checkpoints updated after each batch

### Checkpoint Data Model

```python
@dataclass
class ExtractionCheckpoint:
    extraction_id: str          # Unique identifier for extraction
    source_id: str              # Data source identifier
    source_type: str            # Type of source (csv, database, etc.)
    last_offset: int            # Last successfully processed offset
    last_batch_id: str          # ID of last successfully processed batch
    rows_extracted: int         # Total rows extracted so far
    batches_processed: int      # Total batches processed so far
    status: CheckpointStatus    # ACTIVE, COMPLETED, FAILED, RESUMED
    created_at: datetime        # Checkpoint creation timestamp
    updated_at: datetime        # Last update timestamp
    completed_at: datetime      # Completion timestamp (if completed)
    error_message: str          # Error message (if failed)
    correlation_id: str         # For distributed tracing
    metadata: Dict[str, Any]    # Additional metadata
```

### Checkpoint Status Flow

```
ACTIVE → COMPLETED (successful extraction)
ACTIVE → FAILED (extraction failure)
FAILED → RESUMED (resume after failure)
RESUMED → COMPLETED (successful completion after resume)
```

## Persistence

### ClickHouse Schema

Checkpoints are persisted to ClickHouse using a `ReplacingMergeTree` table:

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
    metadata String  -- JSON serialized
) ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(created_at)
ORDER BY (extraction_id, updated_at);
```

### Key Features

- **ReplacingMergeTree**: Automatically keeps latest version based on `updated_at`
- **Partitioning**: By month for efficient cleanup of old checkpoints
- **Ordering**: By `extraction_id` and `updated_at` for fast lookups
- **In-Memory Cache**: Checkpoints cached in memory for fast access

## Usage

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
source_id = "customers_csv"

config = ExtractionConfig(
    source_id=source_id,
    source_type="csv",
    connection_params={
        "file_path": "/data/customers.csv",
        "encoding": "utf-8",
        "delimiter": ",",
        "has_header": True
    },
    batch_size=1000,
    extraction_id=extraction_id,
    progress_tracker=progress_tracker
)

# Create checkpoint
checkpoint = checkpoint_manager.create_checkpoint(
    extraction_id=extraction_id,
    source_id=source_id,
    source_type="csv",
    metadata={"file_path": "/data/customers.csv"}
)

# Start progress tracking
progress_tracker.start_extraction(
    extraction_id=extraction_id,
    source_id=source_id,
    source_type="csv",
    estimated_total_rows=10000
)

# Extract data in batches
strategy = CSVExtractionStrategy()
offset = 0

try:
    while True:
        # Extract batch
        batch = strategy.extract_batch(config, offset, config.batch_size)
        
        # Process batch (write to bronze layer)
        # ... bronze_writer.write_batch(batch) ...
        
        # Update checkpoint after successful batch processing
        checkpoint_manager.update_checkpoint(
            extraction_id=extraction_id,
            last_offset=offset + batch.total_rows,
            last_batch_id=batch.batch_id,
            rows_extracted=offset + batch.total_rows,
            batches_processed=(offset // config.batch_size) + 1
        )
        
        # Check if done
        if not batch.has_more:
            break
        
        offset += batch.total_rows
    
    # Complete checkpoint
    checkpoint_manager.complete_checkpoint(
        extraction_id=extraction_id,
        final_row_count=offset
    )
    
    # Complete progress tracking
    progress_tracker.complete_extraction(
        extraction_id=extraction_id,
        final_row_count=offset
    )

except Exception as e:
    # Fail checkpoint on error
    checkpoint_manager.fail_checkpoint(
        extraction_id=extraction_id,
        error_message=str(e)
    )
    
    progress_tracker.fail_extraction(
        extraction_id=extraction_id,
        error_message=str(e)
    )
    
    raise
```

### Resuming from Checkpoint

```python
# Check if extraction can be resumed
if checkpoint_manager.can_resume(extraction_id):
    # Resume from checkpoint
    checkpoint = checkpoint_manager.resume_from_checkpoint(extraction_id)
    
    # Continue extraction from last offset
    offset = checkpoint.last_offset
    total_rows = checkpoint.rows_extracted
    batch_count = checkpoint.batches_processed
    
    # Continue extraction loop from offset
    while True:
        batch = strategy.extract_batch(config, offset, config.batch_size)
        
        total_rows += batch.total_rows
        batch_count += 1
        
        checkpoint_manager.update_checkpoint(
            extraction_id=extraction_id,
            last_offset=offset + batch.total_rows,
            last_batch_id=batch.batch_id,
            rows_extracted=total_rows,
            batches_processed=batch_count
        )
        
        if not batch.has_more:
            break
        
        offset += batch.total_rows
    
    # Complete checkpoint
    checkpoint_manager.complete_checkpoint(
        extraction_id=extraction_id,
        final_row_count=total_rows
    )
else:
    print(f"Cannot resume extraction {extraction_id}")
```

### Querying Checkpoints

```python
# Get specific checkpoint
checkpoint = checkpoint_manager.get_checkpoint(extraction_id)
if checkpoint:
    print(f"Status: {checkpoint.status.value}")
    print(f"Progress: {checkpoint.rows_extracted} rows")
    print(f"Last offset: {checkpoint.last_offset}")

# List all active extractions
active_checkpoints = checkpoint_manager.list_active_checkpoints()
for cp in active_checkpoints:
    print(f"{cp.extraction_id}: {cp.rows_extracted} rows extracted")

# Check if can resume
if checkpoint_manager.can_resume(extraction_id):
    print(f"Extraction {extraction_id} can be resumed")
```

### Cleanup Old Checkpoints

```python
# Cleanup completed checkpoints older than 7 days
count = checkpoint_manager.cleanup_old_checkpoints(days=7)
print(f"Cleaned up {count} old checkpoints")
```

## Integration with Progress Tracking

Checkpointing works seamlessly with progress tracking (task 2.2.6):

- **Checkpoint**: Stores state for resume capability (persistent)
- **Progress**: Tracks real-time metrics for monitoring (ephemeral)

Both are updated after each batch:

```python
# Update checkpoint (for resume capability)
checkpoint_manager.update_checkpoint(
    extraction_id=extraction_id,
    last_offset=offset + batch.total_rows,
    last_batch_id=batch.batch_id,
    rows_extracted=total_rows,
    batches_processed=batch_count
)

# Progress is automatically updated by extraction strategy
# via config.progress_tracker
```

## Idempotency Guarantees

### Checkpoint-Based Idempotency

1. **Deterministic Batch IDs**: Same offset always generates same batch_id
2. **Offset-Based Resume**: Resume from exact offset, no duplicate processing
3. **Persistent State**: Checkpoints survive service restarts
4. **Safe Retries**: Failed extractions can be safely retried

### Example: Preventing Duplicate Extraction

```python
# Before starting extraction, check for existing checkpoint
existing_checkpoint = checkpoint_manager.get_checkpoint(extraction_id)

if existing_checkpoint:
    if existing_checkpoint.status == CheckpointStatus.COMPLETED:
        print("Extraction already completed, skipping")
        return
    elif checkpoint_manager.can_resume(extraction_id):
        print("Resuming from checkpoint")
        checkpoint = checkpoint_manager.resume_from_checkpoint(extraction_id)
        offset = checkpoint.last_offset
    else:
        print("Starting new extraction")
        offset = 0
else:
    # Create new checkpoint
    checkpoint_manager.create_checkpoint(
        extraction_id=extraction_id,
        source_id=source_id,
        source_type=source_type
    )
    offset = 0
```

## Error Handling

### Failure Scenarios

1. **Network Failure**: Checkpoint saved before failure, resume from last offset
2. **Service Restart**: Checkpoint loaded from ClickHouse, resume automatically
3. **Data Corruption**: Checkpoint marked as FAILED, manual intervention required
4. **Partial Batch**: Only complete batches are checkpointed, partial batches re-extracted

### Retry Strategy

```python
import time

max_retries = 3
retry_delay = 5  # seconds

for attempt in range(max_retries):
    try:
        # Check if can resume
        if checkpoint_manager.can_resume(extraction_id):
            checkpoint = checkpoint_manager.resume_from_checkpoint(extraction_id)
            offset = checkpoint.last_offset
        else:
            offset = 0
        
        # Run extraction
        run_extraction(extraction_id, offset)
        break
    
    except Exception as e:
        # Fail checkpoint
        checkpoint_manager.fail_checkpoint(
            extraction_id=extraction_id,
            error_message=str(e)
        )
        
        if attempt < max_retries - 1:
            print(f"Retry {attempt + 1}/{max_retries} after {retry_delay}s")
            time.sleep(retry_delay)
            retry_delay *= 2  # Exponential backoff
        else:
            print("Max retries reached, giving up")
            raise
```

## Performance Considerations

### Checkpoint Frequency

- **Too Frequent**: High overhead, slow extraction
- **Too Infrequent**: Large re-extraction on failure
- **Recommended**: After each batch (1000-10000 rows)

### ClickHouse Optimization

- **Batch Inserts**: Checkpoint updates are batched
- **ReplacingMergeTree**: Efficient updates (no DELETE needed)
- **Partitioning**: Fast cleanup of old checkpoints
- **In-Memory Cache**: Reduces ClickHouse queries

### Memory Usage

- **In-Memory Cache**: O(active_extractions)
- **Checkpoint Size**: ~1KB per checkpoint
- **Typical Usage**: <100 active extractions = <100KB memory

## Testing

### Unit Tests

- `test_extraction_checkpoint.py`: Tests checkpoint manager functionality
  - Checkpoint creation and updates
  - Resume capability
  - Status transitions
  - Cleanup operations

### Integration Tests

- `test_checkpoint_integration.py`: Tests integration with extraction strategies
  - CSV extraction with checkpointing
  - Database extraction with checkpointing
  - Resume after failure
  - Idempotency verification

### Running Tests

```bash
# Unit tests
cd etl-final/extractor-service/extractor/engine
python -m pytest test_extraction_checkpoint.py -v

# Integration tests
python -m pytest test_checkpoint_integration.py -v

# All checkpoint tests
python -m pytest test_extraction_checkpoint.py test_checkpoint_integration.py -v
```

## Monitoring and Observability

### Metrics to Track

- **Active Checkpoints**: Number of ongoing extractions
- **Failed Checkpoints**: Number of failed extractions
- **Resume Rate**: Percentage of extractions resumed from checkpoint
- **Checkpoint Update Latency**: Time to persist checkpoint

### Logging

Checkpoints are logged with structured logging:

```json
{
  "timestamp": "2026-02-18T10:30:00Z",
  "level": "INFO",
  "logger": "extraction_checkpoint",
  "message": "Updated checkpoint for extraction ext_123: offset=1000, batch=batch_123, rows=1000",
  "correlation_id": "corr_456"
}
```

### Querying Checkpoint Status

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

-- Extraction progress
SELECT 
    extraction_id,
    source_id,
    rows_extracted,
    batches_processed,
    updated_at
FROM extraction_checkpoints
WHERE extraction_id = 'ext_123'
ORDER BY updated_at DESC
LIMIT 1;
```

## Best Practices

1. **Always Create Checkpoint**: Create checkpoint before starting extraction
2. **Update After Each Batch**: Update checkpoint after successful batch processing
3. **Handle Failures Gracefully**: Mark checkpoint as FAILED on errors
4. **Check Resume Capability**: Always check if extraction can be resumed
5. **Cleanup Old Checkpoints**: Regularly cleanup completed checkpoints
6. **Use Correlation IDs**: Include correlation IDs for distributed tracing
7. **Monitor Checkpoint Status**: Track active and failed checkpoints

## Future Enhancements

1. **Automatic Resume**: Automatically resume failed extractions on service restart
2. **Checkpoint Compression**: Compress checkpoint metadata for large extractions
3. **Multi-Level Checkpoints**: Support checkpoints at file and batch level
4. **Checkpoint Validation**: Validate checkpoint integrity before resume
5. **Checkpoint Replication**: Replicate checkpoints across multiple ClickHouse nodes

## Related Documentation

- [Extraction Progress Tracking](./EXTRACTION_PROGRESS_TRACKING.md)
- [Bronze Layer Implementation](../TASK_2.2.5_BRONZE_WRITE_IMPLEMENTATION.md)
- [Extraction Strategies](./extraction_strategy.py)
- [Requirements Document](../../.kiro/specs/etl-architecture-redesign/requirements.md)
- [Design Document](../../.kiro/specs/etl-architecture-redesign/design.md)
