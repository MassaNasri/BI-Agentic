"""
Silver Schema Demo
Demonstrates usage of the silver layer schema with realistic examples.
"""
from datetime import datetime
from uuid import uuid4
from silver_schema import (
    DataType,
    SilverColumnDefinition,
    SilverTableSchema,
    QualityMetrics,
    SilverRow,
    SilverBatch
)


def demo_schema_creation():
    """Demonstrate creating a silver table schema."""
    print("=" * 80)
    print("DEMO 1: Creating a Silver Table Schema")
    print("=" * 80)
    
    # Define schema for an e-commerce orders table
    orders_schema = SilverTableSchema(
        source_name="orders",
        data_columns=[
            SilverColumnDefinition(
                name="order_id",
                data_type=DataType.INT64,
                nullable=False,
                comment="Unique order identifier"
            ),
            SilverColumnDefinition(
                name="customer_id",
                data_type=DataType.INT64,
                nullable=False,
                comment="Customer who placed the order"
            ),
            SilverColumnDefinition(
                name="order_date",
                data_type=DataType.DATETIME64,
                nullable=False,
                comment="When the order was placed"
            ),
            SilverColumnDefinition(
                name="total_amount",
                data_type=DataType.FLOAT64,
                nullable=False,
                comment="Total order amount in USD"
            ),
            SilverColumnDefinition(
                name="status",
                data_type=DataType.STRING,
                nullable=False,
                default_value="'pending'",
                comment="Order status (pending, shipped, delivered, cancelled)"
            ),
            SilverColumnDefinition(
                name="shipping_address",
                data_type=DataType.STRING,
                nullable=True,
                comment="Shipping address (optional for pickup orders)"
            ),
            SilverColumnDefinition(
                name="items",
                data_type=DataType.ARRAY_STRING,
                nullable=False,
                comment="List of item IDs in the order"
            )
        ]
    )
    
    print(f"\nTable Name: {orders_schema.table_name}")
    print(f"Data Columns: {len(orders_schema.data_columns)}")
    print(f"Partition By: {orders_schema.partition_by}")
    print(f"Order By: {orders_schema.order_by}")
    
    print("\n--- Generated SQL ---")
    print(orders_schema.get_create_table_sql())
    print()


def demo_quality_metrics():
    """Demonstrate quality metrics calculation."""
    print("=" * 80)
    print("DEMO 2: Quality Metrics Calculation")
    print("=" * 80)
    
    # Scenario 1: Perfect quality
    print("\nScenario 1: Perfect Quality Row")
    metrics1 = QualityMetrics(
        completeness_score=1.0,
        validity_score=1.0,
        applied_rules=["trim_strings_v1", "validate_email_v1"],
        warnings=[]
    )
    metrics1.calculate_overall_score()
    print(f"  Completeness: {metrics1.completeness_score:.2f}")
    print(f"  Validity: {metrics1.validity_score:.2f}")
    print(f"  Overall Quality: {metrics1.quality_score:.2f}")
    print(f"  Applied Rules: {metrics1.applied_rules}")
    print(f"  Warnings: {metrics1.warnings}")
    
    # Scenario 2: Good quality with minor issues
    print("\nScenario 2: Good Quality with Minor Issues")
    metrics2 = QualityMetrics(
        completeness_score=0.9,
        validity_score=0.95,
        applied_rules=["trim_strings_v1", "validate_email_v1", "coerce_integer_v1"],
        warnings=["Optional field 'middle_name' was null"]
    )
    metrics2.calculate_overall_score()
    print(f"  Completeness: {metrics2.completeness_score:.2f}")
    print(f"  Validity: {metrics2.validity_score:.2f}")
    print(f"  Overall Quality: {metrics2.quality_score:.2f}")
    print(f"  Warnings: {metrics2.warnings}")
    
    # Scenario 3: Lower quality with multiple issues
    print("\nScenario 3: Lower Quality with Multiple Issues")
    metrics3 = QualityMetrics(
        completeness_score=0.7,
        validity_score=0.8,
        applied_rules=["trim_strings_v1", "validate_email_v1", "coerce_integer_v1", "default_values_v1"],
        warnings=[
            "Field 'phone' was null, using default",
            "Field 'address' failed validation, kept original",
            "Field 'age' was out of range, capped at maximum"
        ]
    )
    metrics3.calculate_overall_score()
    print(f"  Completeness: {metrics3.completeness_score:.2f}")
    print(f"  Validity: {metrics3.validity_score:.2f}")
    print(f"  Overall Quality: {metrics3.quality_score:.2f}")
    print(f"  Warnings: {len(metrics3.warnings)} warnings")
    
    # Custom weights
    print("\nScenario 4: Custom Weights (Equal Importance)")
    metrics4 = QualityMetrics(
        completeness_score=0.8,
        validity_score=0.9
    )
    metrics4.calculate_overall_score(completeness_weight=0.5, validity_weight=0.5)
    print(f"  Completeness: {metrics4.completeness_score:.2f} (weight: 0.5)")
    print(f"  Validity: {metrics4.validity_score:.2f} (weight: 0.5)")
    print(f"  Overall Quality: {metrics4.quality_score:.2f}")
    print()


def demo_silver_row():
    """Demonstrate creating and validating silver rows."""
    print("=" * 80)
    print("DEMO 3: Creating and Validating Silver Rows")
    print("=" * 80)
    
    # Create schema
    schema = SilverTableSchema(
        source_name="customers",
        data_columns=[
            SilverColumnDefinition("customer_id", DataType.INT64, nullable=False),
            SilverColumnDefinition("email", DataType.STRING, nullable=False),
            SilverColumnDefinition("age", DataType.INT32, nullable=True),
            SilverColumnDefinition("is_active", DataType.BOOLEAN, nullable=False)
        ]
    )
    
    # Valid row
    print("\nCreating a valid silver row...")
    metrics = QualityMetrics(
        completeness_score=0.95,
        validity_score=0.98,
        applied_rules=["trim_strings_v1", "validate_email_v1"],
        warnings=[]
    )
    metrics.calculate_overall_score()
    
    row = SilverRow(
        bronze_row_id=uuid4(),
        batch_id="batch_20260217_001",
        cleaned_at=datetime.now(),
        cleaning_version="v1.2.3",
        data={
            "customer_id": 12345,
            "email": "john.doe@example.com",
            "age": 35,
            "is_active": True
        },
        quality_metrics=metrics
    )
    
    is_valid, errors = row.validate(schema)
    print(f"  Valid: {is_valid}")
    print(f"  Row ID: {row.row_id}")
    print(f"  Quality Score: {row.quality_metrics.quality_score:.2f}")
    
    # Convert to dict
    row_dict = row.to_dict()
    print(f"\n  Dictionary keys: {list(row_dict.keys())}")
    print(f"  Lineage columns: _row_id, _bronze_row_id, _batch_id, _cleaned_at, _cleaning_version")
    print(f"  Data columns: customer_id, email, age, is_active")
    print(f"  Quality columns: _quality_score, _applied_rules, _warnings, _completeness_score, _validity_score")
    
    # Invalid row (missing required field)
    print("\n\nCreating an invalid silver row (missing required field)...")
    invalid_row = SilverRow(
        bronze_row_id=uuid4(),
        batch_id="batch_20260217_002",
        cleaned_at=datetime.now(),
        cleaning_version="v1.2.3",
        data={
            "customer_id": 67890,
            # Missing 'email' (required)
            "age": 28,
            "is_active": False
        },
        quality_metrics=QualityMetrics()
    )
    
    is_valid, errors = invalid_row.validate(schema)
    print(f"  Valid: {is_valid}")
    print(f"  Errors: {errors}")
    print()


def demo_silver_batch():
    """Demonstrate creating and processing silver batches."""
    print("=" * 80)
    print("DEMO 4: Creating and Processing Silver Batches")
    print("=" * 80)
    
    # Create schema
    schema = SilverTableSchema(
        source_name="products",
        data_columns=[
            SilverColumnDefinition("product_id", DataType.INT64, nullable=False),
            SilverColumnDefinition("name", DataType.STRING, nullable=False),
            SilverColumnDefinition("price", DataType.FLOAT64, nullable=False),
            SilverColumnDefinition("in_stock", DataType.BOOLEAN, nullable=False)
        ]
    )
    
    # Create batch of rows
    print("\nCreating a batch of 10 silver rows...")
    rows = []
    for i in range(10):
        # Vary quality scores
        completeness = 0.85 + (i % 3) * 0.05
        validity = 0.90 + (i % 2) * 0.05
        
        metrics = QualityMetrics(
            completeness_score=completeness,
            validity_score=validity,
            applied_rules=["trim_strings_v1", "validate_price_v1"],
            warnings=["Price adjusted for currency" if i % 3 == 0 else ""]
        )
        metrics.calculate_overall_score()
        
        row = SilverRow(
            bronze_row_id=uuid4(),
            batch_id="batch_20260217_003",
            cleaned_at=datetime.now(),
            cleaning_version="v1.2.3",
            data={
                "product_id": 1000 + i,
                "name": f"Product {i}",
                "price": 19.99 + i * 5.0,
                "in_stock": i % 2 == 0
            },
            quality_metrics=metrics
        )
        rows.append(row)
    
    # Create batch
    batch = SilverBatch(
        batch_id="batch_20260217_003",
        source_id="products_db",
        rows=rows,
        schema=schema
    )
    
    # Validate batch
    is_valid, errors = batch.validate()
    print(f"  Batch Valid: {is_valid}")
    print(f"  Total Rows: {len(batch.rows)}")
    
    # Get quality summary
    summary = batch.get_quality_summary()
    print(f"\n  Quality Summary:")
    print(f"    Average Quality Score: {summary['avg_quality_score']:.3f}")
    print(f"    Average Completeness: {summary['avg_completeness_score']:.3f}")
    print(f"    Average Validity: {summary['avg_validity_score']:.3f}")
    print(f"    Rows with Warnings: {summary['rows_with_warnings']}")
    print(f"    Warning Rate: {summary['warning_rate']:.1%}")
    
    # Convert to dicts for ClickHouse insertion
    row_dicts = batch.to_dicts()
    print(f"\n  Converted to {len(row_dicts)} dictionaries for ClickHouse insertion")
    print(f"  Sample row keys: {list(row_dicts[0].keys())[:5]}...")
    print()


def demo_type_system():
    """Demonstrate the type system."""
    print("=" * 80)
    print("DEMO 5: Silver Layer Type System")
    print("=" * 80)
    
    print("\nSupported Data Types:")
    print("  Numeric Types:")
    print("    - Int8, Int16, Int32, Int64 (signed integers)")
    print("    - UInt8, UInt16, UInt32, UInt64 (unsigned integers)")
    print("    - Float32, Float64 (floating point)")
    
    print("\n  Text Types:")
    print("    - String (variable length text)")
    
    print("\n  Boolean Types:")
    print("    - Bool (true/false)")
    
    print("\n  Temporal Types:")
    print("    - Date (YYYY-MM-DD)")
    print("    - DateTime (YYYY-MM-DD HH:MM:SS)")
    print("    - DateTime64(3) (with millisecond precision)")
    
    print("\n  Complex Types:")
    print("    - Array(String) (array of strings)")
    print("    - Array(Int64) (array of integers)")
    print("    - Array(Float64) (array of floats)")
    
    print("\n  Identifier Types:")
    print("    - UUID (universally unique identifier)")
    
    print("\nExample: Multi-Type Schema")
    schema = SilverTableSchema(
        source_name="events",
        data_columns=[
            SilverColumnDefinition("event_id", DataType.UUID_TYPE),
            SilverColumnDefinition("user_id", DataType.INT64),
            SilverColumnDefinition("event_type", DataType.STRING),
            SilverColumnDefinition("timestamp", DataType.DATETIME64),
            SilverColumnDefinition("duration_ms", DataType.INT32),
            SilverColumnDefinition("success", DataType.BOOLEAN),
            SilverColumnDefinition("tags", DataType.ARRAY_STRING),
            SilverColumnDefinition("metrics", DataType.ARRAY_FLOAT64)
        ]
    )
    
    print(f"\n  Table: {schema.table_name}")
    print(f"  Columns: {len(schema.data_columns)}")
    for col in schema.data_columns:
        nullable_str = "nullable" if col.nullable else "required"
        print(f"    - {col.name}: {col.data_type.value} ({nullable_str})")
    print()


def demo_lineage_tracing():
    """Demonstrate lineage tracing."""
    print("=" * 80)
    print("DEMO 6: Lineage Tracing")
    print("=" * 80)
    
    # Simulate bronze row
    bronze_row_id = uuid4()
    print(f"\nBronze Row ID: {bronze_row_id}")
    print("  Source: customers.csv")
    print("  Extracted: 2026-02-17 10:30:00")
    print("  Batch: batch_20260217_001")
    
    # Create silver row with lineage
    metrics = QualityMetrics(
        completeness_score=0.92,
        validity_score=0.96,
        applied_rules=["trim_strings_v1", "validate_email_v1", "normalize_phone_v1"],
        warnings=[]
    )
    metrics.calculate_overall_score()
    
    silver_row = SilverRow(
        bronze_row_id=bronze_row_id,
        batch_id="batch_20260217_001",
        cleaned_at=datetime.now(),
        cleaning_version="v1.2.3",
        data={
            "customer_id": 99999,
            "email": "jane.smith@example.com",
            "phone": "+1-555-0123"
        },
        quality_metrics=metrics
    )
    
    print(f"\nSilver Row ID: {silver_row.row_id}")
    print(f"  Bronze Row ID: {silver_row.bronze_row_id}")
    print(f"  Cleaned: {silver_row.cleaned_at}")
    print(f"  Cleaning Version: {silver_row.cleaning_version}")
    print(f"  Quality Score: {silver_row.quality_metrics.quality_score:.2f}")
    print(f"  Applied Rules: {silver_row.quality_metrics.applied_rules}")
    
    print("\nLineage Query (SQL):")
    print(f"""
    SELECT 
        s.customer_id,
        s.email,
        s._quality_score,
        s._cleaning_version,
        b._extracted_at,
        b._source_id,
        b._file_name
    FROM silver_customers s
    JOIN bronze_customers b ON s._bronze_row_id = b._row_id
    WHERE s._row_id = '{silver_row.row_id}';
    """)
    print()


def main():
    """Run all demos."""
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "SILVER SCHEMA DEMONSTRATION" + " " * 31 + "║")
    print("╚" + "=" * 78 + "╝")
    print()
    
    demo_schema_creation()
    demo_quality_metrics()
    demo_silver_row()
    demo_silver_batch()
    demo_type_system()
    demo_lineage_tracing()
    
    print("=" * 80)
    print("DEMO COMPLETE")
    print("=" * 80)
    print("\nKey Takeaways:")
    print("  ✓ Silver layer uses proper types (not all String)")
    print("  ✓ Quality metrics are first-class citizens")
    print("  ✓ Full lineage tracing to bronze layer")
    print("  ✓ Comprehensive validation and error handling")
    print("  ✓ Batch processing with quality summaries")
    print("  ✓ Flexible schema definition with comments")
    print()


if __name__ == "__main__":
    main()
