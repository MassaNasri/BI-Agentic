"""
Quality Score Integration Demo
Demonstrates how quality scoring integrates with silver layer schema.

This demo shows:
1. Creating silver rows with quality metrics
2. Calculating quality scores for data rows
3. Batch quality summary
4. Integration with silver schema validation
"""
import sys
import os
from datetime import datetime
from uuid import uuid4

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from models.silver_schema import (
    SilverTableSchema,
    SilverColumnDefinition,
    DataType,
    QualityMetrics,
    SilverRow,
    SilverBatch
)
from utils.quality_score_calculator import (
    QualityScoreCalculator,
    ValidationSeverity,
    create_validation_issue
)


def demo_perfect_quality_row():
    """Demo: Creating a silver row with perfect quality."""
    print("\n" + "="*70)
    print("DEMO 1: Perfect Quality Row")
    print("="*70)
    
    # Initialize calculator
    calc = QualityScoreCalculator()
    
    # Sample data row
    row_data = {
        "customer_id": 12345,
        "name": "John Doe",
        "email": "john.doe@example.com",
        "phone": "+1-555-0123"
    }
    
    # Define required fields
    required_fields = {"customer_id", "name", "email"}
    
    # Calculate quality score
    quality_result = calc.calculate_quality_score(
        row_data,
        required_fields,
        applied_rules=["trim_strings", "normalize_case", "validate_email"]
    )
    
    print(f"\nData: {row_data}")
    print(f"Required fields: {required_fields}")
    print(f"\nQuality Scores:")
    print(f"  Completeness: {quality_result.completeness_score:.3f}")
    print(f"  Validity: {quality_result.validity_score:.3f}")
    print(f"  Overall: {quality_result.overall_score:.3f}")
    print(f"  Applied rules: {quality_result.applied_rules}")
    print(f"  Warnings: {quality_result.warnings}")
    
    # Create QualityMetrics for silver row
    quality_metrics = QualityMetrics(
        completeness_score=quality_result.completeness_score,
        validity_score=quality_result.validity_score,
        quality_score=quality_result.overall_score,
        applied_rules=quality_result.applied_rules,
        warnings=quality_result.warnings
    )
    
    # Create silver row
    silver_row = SilverRow(
        bronze_row_id=uuid4(),
        batch_id="batch_001",
        cleaned_at=datetime.now(),
        cleaning_version="v1.0",
        data=row_data,
        quality_metrics=quality_metrics
    )
    
    print(f"\n✓ Silver row created with ID: {silver_row.row_id}")
    print(f"  Quality score: {silver_row.quality_metrics.quality_score:.3f}")


def demo_incomplete_data_row():
    """Demo: Row with missing required fields."""
    print("\n" + "="*70)
    print("DEMO 2: Incomplete Data Row")
    print("="*70)
    
    calc = QualityScoreCalculator()
    
    # Row with missing data
    row_data = {
        "customer_id": 67890,
        "name": None,  # Missing!
        "email": "jane@example.com",
        "phone": ""  # Empty string
    }
    
    required_fields = {"customer_id", "name", "email", "phone"}
    
    # Calculate quality score
    quality_result = calc.calculate_quality_score(
        row_data,
        required_fields,
        applied_rules=["trim_strings", "remove_nulls"]
    )
    
    print(f"\nData: {row_data}")
    print(f"Required fields: {required_fields}")
    print(f"\nQuality Scores:")
    print(f"  Completeness: {quality_result.completeness_score:.3f}")
    print(f"    → 2 out of 4 required fields present (name=None, phone='')")
    print(f"  Validity: {quality_result.validity_score:.3f}")
    print(f"  Overall: {quality_result.overall_score:.3f}")
    
    # Create quality metrics
    quality_metrics = QualityMetrics(
        completeness_score=quality_result.completeness_score,
        validity_score=quality_result.validity_score,
        quality_score=quality_result.overall_score,
        applied_rules=quality_result.applied_rules,
        warnings=quality_result.warnings
    )
    
    # Calculate overall score
    quality_metrics.calculate_overall_score()
    
    print(f"\n✓ Quality metrics calculated")
    print(f"  Completeness weight: 0.4")
    print(f"  Validity weight: 0.6")
    print(f"  Overall = (0.4 × {quality_result.completeness_score:.3f}) + (0.6 × {quality_result.validity_score:.3f})")
    print(f"         = {quality_result.overall_score:.3f}")


def demo_validation_errors():
    """Demo: Row with validation errors."""
    print("\n" + "="*70)
    print("DEMO 3: Row with Validation Errors")
    print("="*70)
    
    calc = QualityScoreCalculator()
    
    # Row with invalid data
    row_data = {
        "customer_id": -999,  # Invalid (negative)
        "name": "Alice",
        "email": "not-an-email",  # Invalid format
        "age": 150  # Invalid (too high)
    }
    
    required_fields = {"customer_id", "name", "email"}
    
    # Create validation issues
    validation_results = [
        create_validation_issue(
            "customer_id",
            ValidationSeverity.ERROR,
            "Customer ID cannot be negative",
            rule_id="validate_customer_id"
        ),
        create_validation_issue(
            "email",
            ValidationSeverity.ERROR,
            "Invalid email format",
            rule_id="validate_email"
        ),
        create_validation_issue(
            "age",
            ValidationSeverity.WARNING,
            "Age seems unusually high",
            rule_id="validate_age_range"
        )
    ]
    
    # Calculate quality score
    quality_result = calc.calculate_quality_score(
        row_data,
        required_fields,
        validation_results,
        applied_rules=["validate_customer_id", "validate_email", "validate_age_range"]
    )
    
    print(f"\nData: {row_data}")
    print(f"Required fields: {required_fields}")
    print(f"\nValidation Issues:")
    for issue in quality_result.issues:
        symbol = "✗" if issue.severity == ValidationSeverity.ERROR else "⚠"
        print(f"  {symbol} {issue.severity.value.upper()}: {issue.field_name} - {issue.message}")
    
    print(f"\nQuality Scores:")
    print(f"  Completeness: {quality_result.completeness_score:.3f}")
    print(f"    → All required fields present")
    print(f"  Validity: {quality_result.validity_score:.3f}")
    print(f"    → 2 errors reduce score by 0.2 (1.0 - 0.2 = 0.8)")
    print(f"    → Warning doesn't affect score")
    print(f"  Overall: {quality_result.overall_score:.3f}")
    print(f"\nWarnings: {quality_result.warnings}")


def demo_batch_quality_summary():
    """Demo: Batch quality summary."""
    print("\n" + "="*70)
    print("DEMO 4: Batch Quality Summary")
    print("="*70)
    
    calc = QualityScoreCalculator()
    
    # Create schema
    schema = SilverTableSchema(
        source_name="customers",
        data_columns=[
            SilverColumnDefinition("customer_id", DataType.INT64, nullable=False),
            SilverColumnDefinition("name", DataType.STRING, nullable=False),
            SilverColumnDefinition("email", DataType.STRING, nullable=False)
        ]
    )
    
    # Create sample rows with varying quality
    rows_data = [
        # Perfect quality
        {
            "data": {"customer_id": 1, "name": "Alice", "email": "alice@ex.com"},
            "required": {"customer_id", "name", "email"},
            "validation": []
        },
        # Missing field
        {
            "data": {"customer_id": 2, "name": None, "email": "bob@ex.com"},
            "required": {"customer_id", "name", "email"},
            "validation": []
        },
        # Validation error
        {
            "data": {"customer_id": 3, "name": "Charlie", "email": "invalid"},
            "required": {"customer_id", "name", "email"},
            "validation": [
                create_validation_issue("email", ValidationSeverity.ERROR, "Invalid email")
            ]
        },
        # Perfect quality
        {
            "data": {"customer_id": 4, "name": "Diana", "email": "diana@ex.com"},
            "required": {"customer_id", "name", "email"},
            "validation": []
        },
        # Multiple issues
        {
            "data": {"customer_id": 5, "name": "", "email": "eve@ex.com"},
            "required": {"customer_id", "name", "email"},
            "validation": [
                create_validation_issue("name", ValidationSeverity.WARNING, "Name is empty")
            ]
        }
    ]
    
    # Calculate quality for each row and create silver rows
    silver_rows = []
    quality_results = []
    
    for row_info in rows_data:
        quality_result = calc.calculate_quality_score(
            row_info["data"],
            row_info["required"],
            row_info["validation"]
        )
        quality_results.append(quality_result)
        
        quality_metrics = QualityMetrics(
            completeness_score=quality_result.completeness_score,
            validity_score=quality_result.validity_score,
            quality_score=quality_result.overall_score,
            applied_rules=quality_result.applied_rules,
            warnings=quality_result.warnings
        )
        
        silver_row = SilverRow(
            bronze_row_id=uuid4(),
            batch_id="batch_002",
            cleaned_at=datetime.now(),
            cleaning_version="v1.0",
            data=row_info["data"],
            quality_metrics=quality_metrics
        )
        silver_rows.append(silver_row)
    
    # Create batch
    batch = SilverBatch(
        batch_id="batch_002",
        source_id="source_customers",
        rows=silver_rows,
        schema=schema
    )
    
    # Get batch quality summary
    summary = batch.get_quality_summary()
    
    print(f"\nBatch: {batch.batch_id}")
    print(f"Total rows: {summary['total_rows']}")
    print(f"\nQuality Summary:")
    print(f"  Average completeness: {summary['avg_completeness_score']:.3f}")
    print(f"  Average validity: {summary['avg_validity_score']:.3f}")
    print(f"  Average overall: {summary['avg_quality_score']:.3f}")
    print(f"  Rows with warnings: {summary['rows_with_warnings']} ({summary['warning_rate']:.1%})")
    
    # Calculate detailed summary using calculator
    detailed_summary = calc.calculate_batch_quality_summary(quality_results)
    
    print(f"\nDetailed Summary:")
    print(f"  Min quality score: {detailed_summary['min_overall_score']:.3f}")
    print(f"  Max quality score: {detailed_summary['max_overall_score']:.3f}")
    print(f"  Rows with errors: {detailed_summary['rows_with_errors']}")
    print(f"  Error rate: {detailed_summary['error_rate']:.1%}")
    
    # Show individual row scores
    print(f"\nIndividual Row Scores:")
    for i, row in enumerate(silver_rows, 1):
        print(f"  Row {i}: {row.quality_metrics.quality_score:.3f} "
              f"(C:{row.quality_metrics.completeness_score:.2f}, "
              f"V:{row.quality_metrics.validity_score:.2f})")


def demo_schema_validation_with_quality():
    """Demo: Schema validation integrated with quality scoring."""
    print("\n" + "="*70)
    print("DEMO 5: Schema Validation with Quality Scoring")
    print("="*70)
    
    # Create schema
    schema = SilverTableSchema(
        source_name="orders",
        data_columns=[
            SilverColumnDefinition("order_id", DataType.INT64, nullable=False),
            SilverColumnDefinition("amount", DataType.FLOAT64, nullable=False),
            SilverColumnDefinition("status", DataType.STRING, nullable=False)
        ]
    )
    
    calc = QualityScoreCalculator()
    
    # Create a row with good quality
    row_data = {
        "order_id": 1001,
        "amount": 99.99,
        "status": "completed"
    }
    
    required_fields = {"order_id", "amount", "status"}
    
    quality_result = calc.calculate_quality_score(row_data, required_fields)
    
    quality_metrics = QualityMetrics(
        completeness_score=quality_result.completeness_score,
        validity_score=quality_result.validity_score,
        quality_score=quality_result.overall_score,
        applied_rules=["validate_order"],
        warnings=[]
    )
    
    silver_row = SilverRow(
        bronze_row_id=uuid4(),
        batch_id="batch_003",
        cleaned_at=datetime.now(),
        cleaning_version="v1.0",
        data=row_data,
        quality_metrics=quality_metrics
    )
    
    # Validate row against schema
    is_valid, errors = silver_row.validate(schema)
    
    print(f"\nRow data: {row_data}")
    print(f"\nQuality Metrics:")
    print(f"  Overall score: {silver_row.quality_metrics.quality_score:.3f}")
    print(f"  Completeness: {silver_row.quality_metrics.completeness_score:.3f}")
    print(f"  Validity: {silver_row.quality_metrics.validity_score:.3f}")
    
    print(f"\nSchema Validation:")
    if is_valid:
        print(f"  ✓ Row passes schema validation")
    else:
        print(f"  ✗ Row fails schema validation:")
        for error in errors:
            print(f"    - {error}")
    
    # Convert to dict for ClickHouse insertion
    row_dict = silver_row.to_dict()
    
    print(f"\nRow ready for ClickHouse insertion:")
    print(f"  Lineage columns: _row_id, _bronze_row_id, _batch_id, _cleaned_at, _cleaning_version")
    print(f"  Data columns: {list(row_data.keys())}")
    print(f"  Quality columns: _quality_score, _completeness_score, _validity_score, _applied_rules, _warnings")
    print(f"  Total columns: {len(row_dict)}")


def main():
    """Run all demos."""
    print("\n" + "="*70)
    print("QUALITY SCORE INTEGRATION DEMO")
    print("Demonstrating quality scoring with silver layer schema")
    print("="*70)
    
    demo_perfect_quality_row()
    demo_incomplete_data_row()
    demo_validation_errors()
    demo_batch_quality_summary()
    demo_schema_validation_with_quality()
    
    print("\n" + "="*70)
    print("DEMO COMPLETE")
    print("="*70)
    print("\nKey Takeaways:")
    print("  1. Quality scores are calculated for completeness and validity")
    print("  2. Overall score is a weighted average (default: 40% completeness, 60% validity)")
    print("  3. Quality metrics integrate seamlessly with SilverRow and SilverBatch")
    print("  4. Batch summaries provide aggregate quality statistics")
    print("  5. Schema validation ensures data integrity before insertion")
    print("\nFor more details, see: QUALITY_SCORING_METHODOLOGY.md")
    print()


if __name__ == "__main__":
    main()
