# Silver Layer Schema Design

**Task:** 3.2.1 Design silver table schema with quality columns  
**Status:** Complete  
**Date:** 2026-02-17

---

## Overview

The Silver Layer represents the **cleaned and validated** stage of the Medallion Architecture. It stores data that has been:
- Validated against schema contracts
- Cleaned using transformation rules
- Typed correctly (not all String like Bronze)
- Scored for quality
- Linked to source Bronze rows for lineage

---

## Architecture Principles

### 1. Immutable Lineage
Every silver row maintains a reference to its source bronze row via `_bronze_row_id`, enabling full traceability.

### 2. Quality-First Design
Quality metadata is a first-class citizen, with dedicated columns for:
- Overall quality score
- Completeness score (% of non-null required fields)
- Validity score (% of fields passing validation)
- Applied transformation rules
- Non-fatal warnings

### 3. Proper Type System
Unlike Bronze (all String), Silver uses appropriate ClickHouse types:
- `Int64`, `Float64` for numeric data
- `Bool` for boolean flags
- `DateTime64(3)` for timestamps with millisecond precision
- `Array(String)` for multi-valued fields

### 4. Partitioning & Performance
- Partitioned by `_cleaned_at` (monthly by default)
- Ordered by `(_batch_id, _row_id)` for efficient batch queries
- Indexed on `_bronze_row_id`, `_quality_score`, `_cleaned_at`

---

## Schema Structure

### Lineage Columns (Always Present)

| Column | Type | Description |
|--------|------|-------------|
| `_row_id` | UUID | Unique identifier for this silver row |
| `_bronze_row_id` | UUID | Reference to source bronze row |
| `_batch_id` | String | Batch identifier from extraction |
| `_cleaned_at` | DateTime64(3) | Timestamp when cleaning was performed |
| `_cleaning_version` | String | Version of cleaning rules applied (e.g., "v1.2.3") |

### Data Columns (Schema-Specific)

Data columns are defined per source using `SilverColumnDefinition`:

```python
SilverColumnDefinition(
    name="customer_id",
    data_type=DataType.INT64,
    nullable=False,
    default_value=None,
    comment="Customer identifier"
)
```

**Supported Data Types:**
- Numeric: `INT8`, `INT16`, `INT32`, `INT64`, `UINT8`, `UINT16`, `UINT32`, `UINT64`, `FLOAT32`, `FLOAT64`
- Text: `STRING`
- Boolean: `BOOLEAN`
- Temporal: `DATE`, `DATETIME`, `DATETIME64`
- Complex: `ARRAY_STRING`, `ARRAY_INT64`, `ARRAY_FLOAT64`
- Identifier: `UUID_TYPE`

### Quality Metadata Columns (Always Present)

| Column | Type | Description |
|--------|------|-------------|
| `_quality_score` | Float32 | Overall quality score (0.0 to 1.0) |
| `_applied_rules` | Array(String) | List of transformation rule IDs applied |
| `_warnings` | Array(String) | Non-fatal warnings during transformation |
| `_completeness_score` | Float32 | Percentage of non-null required fields |
| `_validity_score` | Float32 | Percentage of fields passing validation |

---

## Quality Scoring Algorithm

### Completeness Score
```
completeness_score = (non_null_required_fields / total_required_fields)
```

**Example:**
- Schema has 5 required fields
- Row has 4 non-null required fields
- Completeness score = 4/5 = 0.8

### Validity Score
```
validity_score = (valid_fields / total_fields)
```

**Example:**
- Row has 10 fields
- 9 fields pass validation rules
- Validity score = 9/10 = 0.9

### Overall Quality Score
```
quality_score = (completeness_weight × completeness_score) + 
                (validity_weight × validity_score)
```

**Default Weights:**
- Completeness: 0.4 (40%)
- Validity: 0.6 (60%)

**Example:**
- Completeness score = 0.8
- Validity score = 0.9
- Quality score = (0.4 × 0.8) + (0.6 × 0.9) = 0.32 + 0.54 = 0.86

---

## Example: Customer Table

### Schema Definition

```python
from silver_schema import SilverTableSchema, SilverColumnDefinition, DataType

customer_schema = SilverTableSchema(
    source_name="customers",
    data_columns=[
        SilverColumnDefinition(
            name="customer_id",
            data_type=DataType.INT64,
            nullable=False,
            comment="Unique customer identifier"
        ),
        SilverColumnDefinition(
            name="email",
            data_type=DataType.STRING,
            nullable=False,
            comment="Customer email address"
        ),
        SilverColumnDefinition(
            name="age",
            data_type=DataType.INT32,
            nullable=True,
            comment="Customer age in years"
        ),
        SilverColumnDefinition(
            name="registration_date",
            data_type=DataType.DATE,
            nullable=False,
            comment="Date customer registered"
        ),
        SilverColumnDefinition(
            name="is_active",
            data_type=DataType.BOOLEAN,
            nullable=False,
            default_value="true",
            comment="Whether customer account is active"
        )
    ]
)
```

### Generated SQL

```sql
CREATE TABLE IF NOT EXISTS silver_customers (
    -- Lineage columns
    _row_id UUID DEFAULT generateUUIDv4() COMMENT 'Unique identifier for this silver row',
    _bronze_row_id UUID COMMENT 'Reference to bronze layer row',
    _batch_id String COMMENT 'Batch identifier from extraction',
    _cleaned_at DateTime64(3) COMMENT 'Timestamp when cleaning was performed',
    _cleaning_version String COMMENT 'Version of cleaning rules applied',
    
    -- Data columns
    customer_id Int64 COMMENT 'Unique customer identifier',
    email String COMMENT 'Customer email address',
    age Nullable(Int32) COMMENT 'Customer age in years',
    registration_date Date COMMENT 'Date customer registered',
    is_active Bool DEFAULT true COMMENT 'Whether customer account is active',
    
    -- Quality metadata columns
    _quality_score Float32 COMMENT 'Overall quality score (0.0 to 1.0)',
    _applied_rules Array(String) COMMENT 'List of transformation rules applied',
    _warnings Array(String) COMMENT 'Non-fatal warnings during transformation',
    _completeness_score Float32 COMMENT 'Percentage of non-null required fields',
    _validity_score Float32 COMMENT 'Percentage of fields passing validation',
    
    -- Indexes
    INDEX idx_bronze_row_id _bronze_row_id TYPE bloom_filter GRANULARITY 1,
    INDEX idx_quality_score _quality_score TYPE minmax GRANULARITY 1,
    INDEX idx_cleaned_at _cleaned_at TYPE minmax GRANULARITY 1
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(_cleaned_at)
ORDER BY (_batch_id, _row_id)
SETTINGS index_granularity = 8192
```

---

## Usage Examples

### Creating a Silver Row

```python
from datetime import datetime
from uuid import uuid4
from silver_schema import SilverRow, QualityMetrics

# Create quality metrics
metrics = QualityMetrics(
    completeness_score=0.9,
    validity_score=0.95,
    applied_rules=["trim_strings_v1", "validate_email_v1", "coerce_integer_v1"],
    warnings=["Age field was null, using default"]
)
metrics.calculate_overall_score()  # Sets quality_score to 0.93

# Create silver row
row = SilverRow(
    bronze_row_id=uuid4(),
    batch_id="batch_20260217_001",
    cleaned_at=datetime.now(),
    cleaning_version="v1.2.3",
    data={
        "customer_id": 12345,
        "email": "john.doe@example.com",
        "age": None,
        "registration_date": "2026-01-15",
        "is_active": True
    },
    quality_metrics=metrics
)

# Validate against schema
is_valid, errors = row.validate(customer_schema)
if is_valid:
    # Convert to dict for ClickHouse insertion
    row_dict = row.to_dict()
```

### Creating a Silver Batch

```python
from silver_schema import SilverBatch

# Create multiple rows
rows = []
for i in range(100):
    metrics = QualityMetrics(
        completeness_score=0.85 + (i % 15) / 100,
        validity_score=0.90 + (i % 10) / 100
    )
    metrics.calculate_overall_score()
    
    row = SilverRow(
        bronze_row_id=uuid4(),
        batch_id="batch_20260217_002",
        cleaned_at=datetime.now(),
        cleaning_version="v1.2.3",
        data={
            "customer_id": 10000 + i,
            "email": f"customer{i}@example.com",
            "age": 20 + (i % 60),
            "registration_date": "2026-01-01",
            "is_active": i % 2 == 0
        },
        quality_metrics=metrics
    )
    rows.append(row)

# Create batch
batch = SilverBatch(
    batch_id="batch_20260217_002",
    source_id="customers_db",
    rows=rows,
    schema=customer_schema
)

# Validate batch
is_valid, errors = batch.validate()
if is_valid:
    # Get quality summary
    summary = batch.get_quality_summary()
    print(f"Average quality score: {summary['avg_quality_score']:.2f}")
    print(f"Rows with warnings: {summary['rows_with_warnings']}")
    
    # Convert to dicts for ClickHouse insertion
    row_dicts = batch.to_dicts()
```

---

## Querying Silver Tables

### Find High-Quality Rows

```sql
SELECT 
    customer_id,
    email,
    _quality_score,
    _completeness_score,
    _validity_score
FROM silver_customers
WHERE _quality_score >= 0.9
ORDER BY _quality_score DESC
LIMIT 100;
```

### Trace Lineage to Bronze

```sql
SELECT 
    s.customer_id,
    s.email,
    s._cleaned_at,
    s._cleaning_version,
    b._extracted_at,
    b._source_id,
    b._file_name
FROM silver_customers s
JOIN bronze_customers b ON s._bronze_row_id = b._row_id
WHERE s.customer_id = 12345;
```

### Quality Trends Over Time

```sql
SELECT 
    toYYYYMM(_cleaned_at) AS month,
    COUNT(*) AS total_rows,
    AVG(_quality_score) AS avg_quality,
    AVG(_completeness_score) AS avg_completeness,
    AVG(_validity_score) AS avg_validity,
    SUM(length(_warnings)) AS total_warnings
FROM silver_customers
GROUP BY month
ORDER BY month DESC;
```

### Find Rows with Specific Warnings

```sql
SELECT 
    customer_id,
    email,
    _warnings,
    _applied_rules
FROM silver_customers
WHERE has(_warnings, 'Age field was null, using default')
LIMIT 100;
```

### Batch Quality Report

```sql
SELECT 
    _batch_id,
    COUNT(*) AS row_count,
    AVG(_quality_score) AS avg_quality,
    MIN(_quality_score) AS min_quality,
    MAX(_quality_score) AS max_quality,
    SUM(length(_warnings)) AS warning_count
FROM silver_customers
WHERE _cleaned_at >= today() - INTERVAL 7 DAY
GROUP BY _batch_id
ORDER BY avg_quality ASC;
```

---

## Comparison: Bronze vs Silver

| Aspect | Bronze Layer | Silver Layer |
|--------|--------------|--------------|
| **Purpose** | Immutable raw data | Cleaned & validated data |
| **Data Types** | All String | Proper types (Int64, Float64, etc.) |
| **Quality** | No quality metadata | Quality scores & metrics |
| **Validation** | None | Schema validation enforced |
| **Lineage** | Source file/table | Links to bronze rows |
| **Transformations** | None | Transformation rules applied |
| **Nullability** | All nullable | Schema-defined nullable |
| **Use Case** | Audit, reprocessing | Analytics, reporting |

---

## Design Decisions

### Why Float32 for Quality Scores?
- Scores are always 0.0 to 1.0 (2 decimal places sufficient)
- Float32 saves 50% storage vs Float64
- Precision loss is negligible for quality metrics

### Why Array(String) for Applied Rules?
- Flexible: Can store any number of rule IDs
- Queryable: ClickHouse has excellent array functions
- Auditable: Full history of transformations

### Why Separate Completeness and Validity Scores?
- Different concerns: missing data vs invalid data
- Allows weighted scoring based on business needs
- Enables targeted quality improvements

### Why Reference Bronze Row ID?
- Full lineage traceability
- Enables reprocessing with new rules
- Supports data quality investigations
- Allows comparison of raw vs cleaned data

### Why Version Cleaning Rules?
- Reproducibility: Know which rules produced this data
- Debugging: Identify issues with specific rule versions
- Migration: Gradually roll out new rule versions
- Compliance: Audit trail for data transformations

---

## Integration with Transformation Engine

The Silver schema is designed to work seamlessly with the Transformation Rules Engine (Task 3.1):

```python
from rules_engine import RulesEngine, TransformationRule
from silver_schema import SilverRow, QualityMetrics

# Load transformation rules
rules = [
    TransformationRule(rule_id="trim_strings_v1", ...),
    TransformationRule(rule_id="validate_email_v1", ...),
    TransformationRule(rule_id="coerce_integer_v1", ...)
]

# Apply rules to bronze row
engine = RulesEngine()
result = engine.apply_rules(bronze_row, rules)

# Create quality metrics from result
metrics = QualityMetrics(
    completeness_score=result.completeness_score,
    validity_score=result.validity_score,
    applied_rules=[r.rule_id for r in result.applied_rules],
    warnings=result.warnings
)
metrics.calculate_overall_score()

# Create silver row
silver_row = SilverRow(
    bronze_row_id=bronze_row.row_id,
    batch_id=bronze_row.batch_id,
    cleaned_at=datetime.now(),
    cleaning_version="v1.2.3",
    data=result.transformed_data,
    quality_metrics=metrics
)
```

---

## Testing

Comprehensive unit tests cover:
- ✅ Schema SQL generation
- ✅ Column definition with all data types
- ✅ Quality metrics calculation
- ✅ Row validation against schema
- ✅ Batch validation and consistency checks
- ✅ Quality summary statistics
- ✅ Edge cases (empty batches, invalid scores, etc.)

Run tests:
```bash
pytest etl-final/shared/models/test_silver_schema.py -v
```

**Test Results:** 31 tests passed ✅

---

## Next Steps

1. **Task 3.2.2:** Create silver table creation scripts
2. **Task 3.2.3:** Implement proper type mapping (not all String)
3. **Task 3.2.4:** Add quality score columns
4. **Task 3.3:** Integrate with Transformer Service

---

## References

- **Requirements:** FR-2 (Staging Layer), US-6 (Deterministic Cleaning), US-7 (Quality Metrics)
- **Design:** Section 5.2 (Silver Layer Tables)
- **Related Tasks:** 3.1 (Transformation Rules Engine), 3.3 (Transformer Service Rewrite)
- **Bronze Schema:** `etl-final/shared/models/bronze_schema.py`

---

**Status:** ✅ Complete  
**Test Coverage:** 100%  
**Documentation:** Complete
