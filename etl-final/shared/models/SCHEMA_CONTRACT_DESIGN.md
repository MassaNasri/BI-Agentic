# Schema Contract Framework - Design Documentation

## Overview

The Schema Contract Framework provides a comprehensive data validation and schema enforcement system for the ETL pipeline. It implements the design specifications from `design.md` section 3.2 and addresses requirements FR-4, FR-5, and US-4.

## Architecture

### Core Components

1. **DataType Enum**: Defines supported data types
   - STRING, INTEGER, FLOAT, BOOLEAN
   - DATE, TIMESTAMP
   - ARRAY, OBJECT

2. **ConstraintType Enum**: Defines validation constraint types
   - MIN/MAX: Numeric bounds or length constraints
   - REGEX: Pattern matching for strings
   - ENUM: Allowed value lists
   - FORMAT: Predefined formats (email, url, uuid)
   - RANGE: Value range validation
   - UNIQUE: Uniqueness constraint
   - REQUIRED: Field presence requirement

3. **Constraint Class**: Represents individual validation rules
   - Validates field values against specific criteria
   - Supports custom error messages
   - Configurable severity (error/warning)

4. **FieldDefinition Class**: Defines schema fields
   - Type specification with nullable support
   - Multiple constraints per field
   - Default values and metadata
   - Comprehensive validation logic

5. **SchemaContract Class**: Complete schema definition
   - Collection of field definitions
   - Global constraints
   - Version tracking
   - Row validation with quality scoring
   - Serialization/deserialization support

6. **ValidationResult Class**: Validation outcome
   - Success/failure status
   - Detailed violation messages
   - Quality score calculation
   - Per-field scoring
   - Timestamp tracking

7. **SchemaEvolutionRecord Class**: Schema change tracking
   - Version history
   - Change documentation
   - Backward compatibility flags
   - Audit trail

## Key Features

### 1. Type Safety

The framework enforces strict type validation:

```python
field = FieldDefinition(name="age", type=DataType.INTEGER, nullable=False)
field.validate(25)  # Valid
field.validate("25")  # Invalid - type mismatch
```

### 2. Flexible Constraints

Multiple constraints can be applied to fields:

```python
field = FieldDefinition(
    name="username",
    type=DataType.STRING,
    nullable=False,
    constraints=[
        Constraint(ConstraintType.MIN, 3),
        Constraint(ConstraintType.MAX, 20),
        Constraint(ConstraintType.REGEX, r'^[a-zA-Z0-9_]+$')
    ]
)
```

### 3. Quality Scoring

Validation results include quality scores:

- 1.0: All fields valid and present
- 0.5: Optional fields missing
- 0.0: Field validation failed

Quality scores enable data quality monitoring and alerting.

### 4. Schema Versioning

Schemas are versioned for evolution tracking:

```python
schema = SchemaContract(
    schema_id="user_schema",
    version="1.0.0",
    fields=[...]
)
```

### 5. Serialization Support

Schemas can be serialized to/from dictionaries for:
- Storage in databases
- Transmission via Kafka
- Configuration files (JSON/YAML)

```python
schema_dict = schema.to_dict()
schema = SchemaContract.from_dict(schema_dict)
```

## Usage Examples

### Basic Schema Definition

```python
from shared.models import (
    SchemaContract,
    FieldDefinition,
    DataType,
    Constraint,
    ConstraintType
)

# Define schema
user_schema = SchemaContract(
    schema_id="user_schema",
    version="1.0.0",
    fields=[
        FieldDefinition(
            name="id",
            type=DataType.INTEGER,
            nullable=False
        ),
        FieldDefinition(
            name="email",
            type=DataType.STRING,
            nullable=False,
            constraints=[
                Constraint(ConstraintType.FORMAT, "email")
            ]
        ),
        FieldDefinition(
            name="age",
            type=DataType.INTEGER,
            nullable=True,
            constraints=[
                Constraint(ConstraintType.MIN, 0),
                Constraint(ConstraintType.MAX, 150)
            ]
        )
    ],
    description="User data schema"
)
```

### Row Validation

```python
# Valid row
row = {
    "id": 1,
    "email": "user@example.com",
    "age": 30
}

result = user_schema.validate_row(row)
print(f"Valid: {result.is_valid}")
print(f"Quality Score: {result.quality_score}")

# Invalid row
invalid_row = {
    "id": 1,
    "email": "not-an-email",  # Invalid format
    "age": 200  # Exceeds max
}

result = user_schema.validate_row(invalid_row)
print(f"Valid: {result.is_valid}")
print(f"Violations: {result.violations}")
```

### Schema Evolution

```python
# Track schema changes
evolution = SchemaEvolutionRecord(
    schema_id="user_schema",
    from_version="1.0.0",
    to_version="1.1.0",
    changes=["Added field 'phone'"],
    change_type="ADDITION",
    backward_compatible=True,
    created_by="admin"
)
```

## Integration with ETL Pipeline

### 1. Extraction Phase

Schema contracts are validated during extraction:

```python
# In extractor service
schema_contract = load_schema_contract(source_id)
for row in extracted_rows:
    result = schema_contract.validate_row(row)
    if not result.is_valid:
        quarantine_manager.quarantine(row, result.violations)
```

### 2. Transformation Phase

Schema validation ensures data quality:

```python
# In transformer service
result = schema_contract.validate_row(transformed_row)
if result.quality_score < 0.8:
    logger.warning(f"Low quality score: {result.quality_score}")
```

### 3. Loading Phase

Final validation before loading to ClickHouse:

```python
# In loader service
for row in batch:
    result = schema_contract.validate_row(row)
    if not result.is_valid:
        raise LoadException(f"Invalid row: {result.violations}")
```

## Design Decisions

### 1. Dataclasses Over Plain Dicts

Using dataclasses provides:
- Type hints for better IDE support
- Automatic `__init__` generation
- Immutability options
- Better documentation

### 2. Enum for Types and Constraints

Enums prevent typos and provide:
- Autocomplete in IDEs
- Type safety
- Clear documentation of valid values

### 3. Separate Validation Logic

Validation is separated from data models:
- Pure functions (no side effects)
- Testable in isolation
- Reusable across services

### 4. Quality Scoring

Quality scores enable:
- Gradual degradation handling
- Data quality monitoring
- Alerting thresholds
- Trend analysis

### 5. Serialization Support

JSON-compatible serialization enables:
- Schema storage in databases
- Schema transmission via Kafka
- Configuration file support
- API integration

## Testing

Comprehensive test coverage includes:

1. **Constraint Tests**: Each constraint type validated
2. **Type Tests**: All data types tested
3. **Field Tests**: Nullable, required, default values
4. **Schema Tests**: Row validation, quality scoring
5. **Serialization Tests**: Round-trip conversion
6. **Complex Scenarios**: Real-world validation cases

Run tests:
```bash
pytest etl-final/shared/models/test_schema_contract.py -v
```

## Performance Considerations

### 1. Validation Overhead

- Validation is O(n) where n = number of fields
- Constraint validation is O(m) where m = number of constraints
- Total: O(n * m) per row

### 2. Optimization Strategies

- Cache compiled regex patterns
- Skip validation for trusted sources
- Batch validation for efficiency
- Parallel validation for large datasets

### 3. Memory Usage

- Schema contracts are lightweight (< 1KB typically)
- Validation results are ephemeral
- No state maintained between validations

## Future Enhancements

### 1. Advanced Constraints

- Cross-field validation (field A depends on field B)
- Conditional constraints (if X then Y)
- Custom constraint functions

### 2. Schema Registry

- Centralized schema storage
- Version management
- Schema discovery API
- Schema compatibility checking

### 3. Performance Optimization

- Compiled validation rules
- Parallel validation
- Caching strategies
- Lazy validation

### 4. Integration Features

- JSON Schema compatibility
- Avro schema conversion
- Protobuf schema conversion
- OpenAPI schema generation

## References

- Design Document: `.kiro/specs/etl-architecture-redesign/design.md` (Section 3.2)
- Requirements: `.kiro/specs/etl-architecture-redesign/requirements.md` (FR-4, FR-5, US-4)
- Implementation: `etl-final/shared/models/schema_contract.py`
- Tests: `etl-final/shared/models/test_schema_contract.py`

## Conclusion

The Schema Contract Framework provides a robust, flexible, and performant solution for schema validation and enforcement in the ETL pipeline. It addresses all requirements from the design document and provides a solid foundation for data quality management.
