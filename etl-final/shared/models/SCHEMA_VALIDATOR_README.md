# SchemaValidator Implementation

## Overview

The `SchemaValidator` class provides validation services for the ETL pipeline, ensuring data conforms to defined schema contracts. It's part of the Schema Contract Framework (Phase 2, Task 2.3.2).

## Features

### Core Functionality
- **Single Row Validation**: Validate individual data rows against schema contracts
- **Batch Validation**: Validate multiple rows with aggregated results
- **Quality Scoring**: Calculate quality scores for data (0.0 to 1.0)
- **Schema Caching**: Optional caching for improved performance
- **Filtering Methods**: Convenience methods to filter valid/invalid rows

### Key Components

1. **SchemaValidator Class**
   - Main validation service
   - Supports caching for performance
   - Provides detailed validation results

2. **BatchValidationResult Class**
   - Aggregates validation results for batches
   - Tracks valid/invalid row counts
   - Calculates overall quality scores

## Usage Examples

### Basic Validation

```python
from shared.models import SchemaValidator, SchemaContract, FieldDefinition, DataType

# Create schema
schema = SchemaContract(
    schema_id="user_schema",
    version="1.0.0",
    fields=[
        FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
        FieldDefinition(name="email", type=DataType.STRING, nullable=False)
    ]
)

# Create validator
validator = SchemaValidator(cache_schemas=True)

# Validate single row
row = {"id": 1, "email": "user@example.com"}
result = validator.validate(row, schema)

if result.is_valid:
    print(f"Quality score: {result.quality_score}")
else:
    print(f"Errors: {result.violations}")
```

### Batch Validation

```python
# Validate multiple rows
rows = [
    {"id": 1, "email": "user1@example.com"},
    {"id": 2, "email": "user2@example.com"},
    {"id": 3, "email": "invalid-email"}
]

batch_result = validator.validate_batch(rows, schema)

print(f"Valid: {batch_result.valid_rows}/{batch_result.total_rows}")
print(f"Overall quality: {batch_result.overall_quality_score:.2%}")

# Check individual results
for i, validation in enumerate(batch_result.validation_results):
    if not validation.is_valid:
        print(f"Row {i} errors: {validation.violations}")
```

### Filtering Invalid Rows (for Quarantine)

```python
# Get only invalid rows for quarantine
invalid_rows = validator.get_invalid_rows(rows, schema)

for idx, row, result in invalid_rows:
    print(f"Row {idx} failed: {result.violations}")
    # Send to quarantine
    quarantine_manager.quarantine(row, result.violations)
```

### Filtering Valid Rows (for Processing)

```python
# Get only valid rows for processing
valid_rows = validator.get_valid_rows(rows, schema)

for idx, row, result in valid_rows:
    print(f"Row {idx} quality: {result.quality_score:.2%}")
    # Process the valid row
    process_row(row)
```

### Schema Caching

```python
# Cache a schema for repeated use
validator.cache_schema(schema)

# Retrieve cached schema
cached = validator.get_cached_schema("user_schema", "1.0.0")

# Get cache statistics
stats = validator.get_cache_stats()
print(f"Cached schemas: {stats['cached_schemas']}")

# Clear cache
validator.clear_cache()
```

## Integration with ETL Pipeline

### Transformer Service Integration

```python
class TransformerService:
    def __init__(self):
        self.validator = SchemaValidator(cache_schemas=True)
        self.quarantine_manager = QuarantineManager()
    
    def process_bronze_batch(self, bronze_batch):
        # Validate batch
        batch_result = self.validator.validate_batch(
            bronze_batch.rows,
            bronze_batch.schema_contract
        )
        
        # Separate valid and invalid rows
        valid_rows = []
        for i, result in enumerate(batch_result.validation_results):
            if result.is_valid:
                valid_rows.append(bronze_batch.rows[i])
            else:
                # Quarantine invalid row
                self.quarantine_manager.quarantine(
                    bronze_batch.rows[i],
                    result.violations
                )
        
        return valid_rows
```

## Quality Score Calculation

Quality scores are calculated based on:
- **Field Validity**: Each valid field scores 1.0
- **Invalid Fields**: Invalid fields score 0.0
- **Missing Optional Fields**: Score 0.5 (partial credit)
- **Overall Score**: Average of all field scores

Example:
- 3 fields total
- 2 valid fields (2.0)
- 1 missing optional field (0.5)
- Quality score = 2.5 / 3 = 0.833 (83.3%)

## Performance Considerations

### Caching
- Enable caching for schemas used repeatedly
- Cache key format: `{schema_id}:{version}`
- Clear cache periodically to prevent memory growth

### Batch Processing
- Process rows in batches for better performance
- Use `stop_on_first_error=True` for fail-fast validation
- Consider parallel processing for large batches

## Testing

Comprehensive test suite includes:
- 33 unit tests covering all functionality
- Tests for constraints (MIN, MAX, REGEX, FORMAT, etc.)
- Batch validation tests
- Caching tests
- Quality score calculation tests
- Edge case handling

Run tests:
```bash
pytest etl-final/shared/models/test_schema_validator.py -v
```

## Design Alignment

This implementation aligns with:
- **Requirements**: FR-4 (Schema Validation), FR-5 (Data Contracts), US-4 (Schema enforcement)
- **Design**: Section 3.2 (Schema Validation Framework)
- **Architecture**: Stateless, pure functional validation
- **Principles**: Fail Fast, Observability Built-In

## Related Components

- **SchemaContract**: Defines data contracts (task 2.3.1 - completed)
- **QuarantineManager**: Handles invalid data (task 3.4.2 - pending)
- **TransformerService**: Uses validator for data cleaning (task 3.3.3 - pending)
- **Schema Registry**: Manages schema versions (task 2.3.3 - pending)

## Next Steps

1. Implement Schema Registry Service (task 2.3.3)
2. Add schema versioning support (task 2.3.4)
3. Implement schema evolution detection (task 2.3.5)
4. Integrate with Transformer Service (task 3.3.5)
