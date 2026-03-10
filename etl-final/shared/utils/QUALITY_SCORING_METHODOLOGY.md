# Quality Scoring Methodology

## Overview

The ETL pipeline implements comprehensive data quality scoring for the silver layer. Each row receives quality metrics that quantify data completeness, validity, and overall quality. This document describes the methodology used to calculate these scores.

## Quality Dimensions

### 1. Completeness Score

**Definition:** Measures the percentage of required fields that contain non-null, non-empty values.

**Formula:**
```
Completeness Score = (Number of non-null required fields) / (Total required fields)
```

**Range:** 0.0 to 1.0
- 1.0 = Perfect completeness (all required fields present)
- 0.0 = No required fields present

**Rules:**
- Only required (non-nullable) fields are considered
- NULL values count as missing
- Empty strings (after trimming whitespace) count as missing
- Optional fields don't affect the completeness score

**Example:**
```python
# Row with 3 required fields
row = {
    "customer_id": 123,      # Present ✓
    "name": None,            # Missing ✗
    "email": "john@ex.com"   # Present ✓
}
required_fields = {"customer_id", "name", "email"}

# Completeness = 2/3 = 0.667
```

### 2. Validity Score

**Definition:** Measures how well the data passes validation rules and constraints.

**Formula:**
```
Validity Score = max(0.0, 1.0 - (error_count * 0.1))
```

**Range:** 0.0 to 1.0
- 1.0 = Perfect validity (no validation errors)
- 0.0 = 10 or more validation errors

**Rules:**
- Each ERROR-level validation issue reduces the score by 0.1
- WARNING-level issues are logged but don't affect the score
- INFO-level issues are informational only
- Score cannot go below 0.0

**Validation Issue Severity Levels:**

| Severity | Impact on Score | Use Case |
|----------|----------------|----------|
| ERROR | -0.1 per error | Critical validation failures (invalid format, constraint violation) |
| WARNING | No impact | Non-critical issues (unusual values, missing optional fields) |
| INFO | No impact | Informational messages (applied transformations, data notes) |

**Example:**
```python
# Row with validation issues
validation_results = [
    ValidationIssue("email", ERROR, "Invalid email format"),
    ValidationIssue("age", ERROR, "Age out of range"),
    ValidationIssue("phone", WARNING, "Phone format unusual")
]

# Validity = 1.0 - (2 errors * 0.1) = 0.8
# Warning doesn't affect score
```

### 3. Overall Quality Score

**Definition:** Weighted combination of completeness and validity scores.

**Formula:**
```
Overall Score = (completeness_weight * Completeness) + (validity_weight * Validity)
```

**Default Weights:**
- Completeness: 0.4 (40%)
- Validity: 0.6 (60%)

**Rationale:** Validity is weighted higher because invalid data is more problematic than missing data. Missing data can be handled with defaults or imputation, but invalid data can cause downstream processing errors.

**Range:** 0.0 to 1.0
- 1.0 = Perfect quality
- 0.8-0.99 = High quality
- 0.6-0.79 = Medium quality
- 0.4-0.59 = Low quality
- 0.0-0.39 = Very low quality

**Example:**
```python
# Row with partial completeness and some validation errors
completeness_score = 0.75  # 3/4 required fields present
validity_score = 0.90      # 1 validation error

# Overall = (0.4 * 0.75) + (0.6 * 0.90)
#         = 0.30 + 0.54
#         = 0.84 (High quality)
```

## Quality Metadata Columns

The silver layer includes the following quality metadata columns:

| Column | Type | Description |
|--------|------|-------------|
| `_quality_score` | Float32 | Overall quality score (0.0 to 1.0) |
| `_completeness_score` | Float32 | Completeness score (0.0 to 1.0) |
| `_validity_score` | Float32 | Validity score (0.0 to 1.0) |
| `_applied_rules` | Array(String) | List of transformation rule IDs applied |
| `_warnings` | Array(String) | List of warning messages |

## Batch Quality Summary

For each batch of rows, aggregate quality metrics are calculated:

| Metric | Description |
|--------|-------------|
| `avg_completeness_score` | Average completeness across all rows |
| `avg_validity_score` | Average validity across all rows |
| `avg_overall_score` | Average overall quality across all rows |
| `min_overall_score` | Minimum quality score in batch |
| `max_overall_score` | Maximum quality score in batch |
| `rows_with_warnings` | Count of rows with warnings |
| `rows_with_errors` | Count of rows with validation errors |
| `warning_rate` | Percentage of rows with warnings |
| `error_rate` | Percentage of rows with validation errors |

## Usage Examples

### Example 1: Perfect Quality Row

```python
from quality_score_calculator import QualityScoreCalculator

calc = QualityScoreCalculator()

row = {
    "customer_id": 12345,
    "name": "John Doe",
    "email": "john.doe@example.com",
    "phone": "+1-555-0123"
}

required_fields = {"customer_id", "name", "email"}

result = calc.calculate_quality_score(row, required_fields)

# Result:
# completeness_score: 1.0 (all required fields present)
# validity_score: 1.0 (no validation errors)
# overall_score: 1.0 (perfect quality)
```

### Example 2: Row with Missing Data

```python
row = {
    "customer_id": 12345,
    "name": None,  # Missing
    "email": "john.doe@example.com"
}

required_fields = {"customer_id", "name", "email"}

result = calc.calculate_quality_score(row, required_fields)

# Result:
# completeness_score: 0.667 (2/3 required fields present)
# validity_score: 1.0 (no validation errors)
# overall_score: 0.867 (0.4 * 0.667 + 0.6 * 1.0)
```

### Example 3: Row with Validation Errors

```python
from quality_score_calculator import create_validation_issue, ValidationSeverity

row = {
    "customer_id": 12345,
    "name": "John Doe",
    "email": "invalid-email"  # Invalid format
}

required_fields = {"customer_id", "name", "email"}

validation_results = [
    create_validation_issue(
        "email",
        ValidationSeverity.ERROR,
        "Invalid email format"
    )
]

result = calc.calculate_quality_score(
    row,
    required_fields,
    validation_results
)

# Result:
# completeness_score: 1.0 (all required fields present)
# validity_score: 0.9 (1 validation error)
# overall_score: 0.94 (0.4 * 1.0 + 0.6 * 0.9)
```

### Example 4: Batch Quality Summary

```python
# Calculate quality for multiple rows
results = []
for row in batch_rows:
    result = calc.calculate_quality_score(
        row,
        required_fields,
        validation_results_for_row
    )
    results.append(result)

# Get batch summary
summary = calc.calculate_batch_quality_summary(results)

print(f"Batch Quality Summary:")
print(f"  Total rows: {summary['total_rows']}")
print(f"  Average quality: {summary['avg_overall_score']:.3f}")
print(f"  Min quality: {summary['min_overall_score']:.3f}")
print(f"  Max quality: {summary['max_overall_score']:.3f}")
print(f"  Rows with errors: {summary['rows_with_errors']}")
print(f"  Error rate: {summary['error_rate']:.1%}")
```

## Quality Thresholds and Actions

Recommended quality thresholds for automated actions:

| Quality Score | Action | Description |
|---------------|--------|-------------|
| 0.95 - 1.0 | Accept | Excellent quality, load to silver layer |
| 0.80 - 0.94 | Accept with warning | Good quality, log warnings for review |
| 0.60 - 0.79 | Review | Medium quality, flag for manual review |
| 0.40 - 0.59 | Quarantine | Low quality, quarantine for investigation |
| 0.0 - 0.39 | Reject | Very low quality, reject and alert |

## Customization

### Custom Weights

You can customize the weights for completeness and validity:

```python
# Equal weighting
calc = QualityScoreCalculator(
    completeness_weight=0.5,
    validity_weight=0.5
)

# Prioritize completeness
calc = QualityScoreCalculator(
    completeness_weight=0.7,
    validity_weight=0.3
)
```

### Custom Validation Rules

Implement custom validation logic and create validation issues:

```python
def validate_email(email: str) -> Optional[ValidationIssue]:
    """Custom email validation."""
    if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
        return create_validation_issue(
            "email",
            ValidationSeverity.ERROR,
            "Invalid email format",
            rule_id="validate_email_v1"
        )
    return None

# Use in quality calculation
validation_results = []
if email_issue := validate_email(row['email']):
    validation_results.append(email_issue)

result = calc.calculate_quality_score(
    row,
    required_fields,
    validation_results
)
```

## Integration with Silver Layer

Quality scores are automatically calculated during transformation and stored in the silver layer:

```python
from silver_schema import SilverRow, QualityMetrics

# Create quality metrics from calculation result
quality_metrics = QualityMetrics(
    completeness_score=result.completeness_score,
    validity_score=result.validity_score,
    quality_score=result.overall_score,
    applied_rules=result.applied_rules,
    warnings=result.warnings
)

# Create silver row with quality metrics
silver_row = SilverRow(
    bronze_row_id=bronze_row_id,
    batch_id=batch_id,
    cleaned_at=datetime.now(),
    cleaning_version="v1.0",
    data=cleaned_data,
    quality_metrics=quality_metrics
)
```

## Monitoring and Alerting

Quality scores enable proactive monitoring:

1. **Trend Analysis:** Track average quality scores over time
2. **Anomaly Detection:** Alert when quality drops below baseline
3. **Source Comparison:** Compare quality across different data sources
4. **Rule Effectiveness:** Measure impact of transformation rules on quality

Example monitoring queries:

```sql
-- Average quality by source over last 7 days
SELECT
    _source_id,
    toDate(_cleaned_at) as date,
    avg(_quality_score) as avg_quality,
    avg(_completeness_score) as avg_completeness,
    avg(_validity_score) as avg_validity
FROM silver_customers
WHERE _cleaned_at >= now() - INTERVAL 7 DAY
GROUP BY _source_id, date
ORDER BY date DESC, _source_id;

-- Rows with low quality scores
SELECT
    _row_id,
    _batch_id,
    _quality_score,
    _warnings
FROM silver_customers
WHERE _quality_score < 0.8
ORDER BY _quality_score ASC
LIMIT 100;
```

## References

- Design Document: `design.md` section 5.2 (Silver Layer Tables)
- Requirements: US-7 (Data Quality Metrics)
- Implementation: `quality_score_calculator.py`
- Tests: `test_quality_score_calculator.py`
