"""
Demo: Type Mapper Integration with Silver Table Creation
Shows how type mapping works end-to-end from bronze to silver layer.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.type_mapper import TypeMapper, TypeInferenceStrategy, create_silver_schema_from_bronze
from models.silver_schema import DataType, SilverTableSchema
from unittest.mock import Mock


def demo_basic_type_inference():
    """Demonstrate basic type inference for different data types."""
    print("\n" + "=" * 70)
    print("DEMO 1: Basic Type Inference")
    print("=" * 70)
    
    mapper = TypeMapper(strategy=TypeInferenceStrategy.CONSERVATIVE)
    
    # Test different column types
    test_cases = [
        ("user_id", ["1", "2", "3", "10", "50"], "Small unsigned integer"),
        ("age", ["25", "30", "35", "40", "45"], "Small signed integer"),
        ("salary", ["50000.50", "60000.75", "70000.00"], "Float"),
        ("is_active", ["true", "false", "true", "false"], "Boolean"),
        ("created_at", ["2024-01-15T10:30:00", "2024-02-20T14:45:30"], "DateTime"),
        ("birth_date", ["1990-01-15", "1985-06-20", "1992-03-10"], "Date"),
        ("tags", ["1,2,3", "4,5,6", "7,8,9"], "Integer Array"),
        ("categories", ["red,green,blue", "cat,dog,bird"], "String Array"),
        ("zip_code", ["00501", "01234", "02345"], "String (leading zeros)"),
        ("email", ["user@example.com", "admin@test.org"], "String"),
    ]
    
    for col_name, sample_values, description in test_cases:
        data_type, confidence = mapper.infer_column_type(col_name, sample_values)
        print(f"\n{col_name:15} ({description})")
        print(f"  → Type: {data_type.value:20} Confidence: {confidence:.1%}")


def demo_confidence_strategies():
    """Demonstrate different confidence strategies."""
    print("\n" + "=" * 70)
    print("DEMO 2: Confidence Strategies")
    print("=" * 70)
    
    # Sample data with 96% integers, 4% strings
    mixed_data = ["1", "2", "3", "4", "5"] * 24 + ["abc"] * 5
    
    strategies = [
        (TypeInferenceStrategy.STRICT, "99%+ confidence required"),
        (TypeInferenceStrategy.CONSERVATIVE, "95%+ confidence required (default)"),
        (TypeInferenceStrategy.LENIENT, "90%+ confidence required"),
    ]
    
    print(f"\nSample data: 96% integers, 4% strings")
    print(f"Total values: {len(mixed_data)}")
    
    for strategy, description in strategies:
        mapper = TypeMapper(strategy=strategy)
        data_type, confidence = mapper.infer_column_type("mixed_col", mixed_data)
        print(f"\n{strategy.value.upper():15} ({description})")
        print(f"  → Type: {data_type.value:20} Confidence: {confidence:.1%}")


def demo_integer_size_selection():
    """Demonstrate intelligent integer size selection."""
    print("\n" + "=" * 70)
    print("DEMO 3: Integer Size Selection")
    print("=" * 70)
    
    mapper = TypeMapper()
    
    test_cases = [
        ("tiny_id", ["1", "2", "3", "10"], "UInt8", "0-255"),
        ("small_id", ["1000", "2000", "5000"], "UInt16", "0-65,535"),
        ("medium_id", ["100000", "200000", "500000"], "UInt32", "0-4B"),
        ("large_id", ["10000000000", "20000000000"], "UInt64", "0-18 quintillion"),
        ("tiny_num", ["-10", "0", "10", "50"], "Int8", "-128 to 127"),
        ("small_num", ["-1000", "0", "1000"], "Int16", "-32K to 32K"),
        ("medium_num", ["-100000", "0", "100000"], "Int32", "-2B to 2B"),
        ("large_num", ["-10000000000", "0", "10000000000"], "Int64", "-9Q to 9Q"),
    ]
    
    print("\nAutomatic size selection based on value range:")
    
    for col_name, sample_values, expected_type, range_desc in test_cases:
        data_type, confidence = mapper.infer_column_type(col_name, sample_values)
        print(f"\n{col_name:15} Range: {range_desc}")
        print(f"  → Type: {data_type.value:20} (Expected: {expected_type})")


def demo_schema_creation_from_bronze():
    """Demonstrate creating silver schema from bronze table."""
    print("\n" + "=" * 70)
    print("DEMO 4: Silver Schema Creation from Bronze Table")
    print("=" * 70)
    
    # Mock ClickHouse client
    mock_client = Mock()
    
    # Simulate bronze table with various column types
    mock_client.execute.side_effect = [
        # DESCRIBE TABLE response
        [
            ("_row_id", "UUID", "", "", "", "", ""),
            ("_batch_id", "String", "", "", "", "", ""),
            ("_source_id", "String", "", "", "", "", ""),
            ("_extracted_at", "DateTime64(3)", "", "", "", "", ""),
            ("user_id", "String", "", "", "", "", ""),
            ("username", "String", "", "", "", "", ""),
            ("age", "String", "", "", "", "", ""),
            ("salary", "String", "", "", "", "", ""),
            ("is_active", "String", "", "", "", "", ""),
            ("created_at", "String", "", "", "", "", ""),
            ("tags", "String", "", "", "", "", ""),
        ],
        # SELECT sample data response
        [
            ("1", "john_doe", "25", "50000.50", "true", "2024-01-15T10:30:00", "1,2,3"),
            ("2", "jane_smith", "30", "60000.75", "false", "2024-02-20T14:45:30", "4,5,6"),
            ("3", "bob_jones", "35", "70000.00", "true", "2024-03-10T08:15:45", "7,8,9"),
            ("4", "alice_brown", "28", "55000.25", "false", "2024-04-05T12:20:15", "10,11,12"),
            ("5", "charlie_davis", "42", "80000.00", "true", "2024-05-12T16:35:50", "13,14,15"),
        ]
    ]
    
    # Create silver schema
    print("\nAnalyzing bronze_users table...")
    schema = create_silver_schema_from_bronze(
        source_name="users",
        bronze_table_name="bronze_users",
        clickhouse_client=mock_client,
        strategy=TypeInferenceStrategy.CONSERVATIVE,
        sample_size=1000
    )
    
    print(f"\nSilver Schema for '{schema.source_name}':")
    print(f"Table name: silver_{schema.source_name}")
    print(f"\nData Columns ({len(schema.data_columns)}):")
    
    for col in schema.data_columns:
        nullable_str = "NULL" if col.nullable else "NOT NULL"
        print(f"  {col.name:15} {col.data_type.value:20} {nullable_str:10} # {col.comment}")
    
    print(f"\nPartitioning: {schema.partition_by}")
    print(f"Ordering: {', '.join(schema.order_by)}")
    
    # Show SQL generation
    print("\n" + "-" * 70)
    print("Generated SQL Column Definitions:")
    print("-" * 70)
    for col in schema.data_columns:
        print(f"  {col.to_sql()},")


def demo_edge_cases():
    """Demonstrate handling of edge cases."""
    print("\n" + "=" * 70)
    print("DEMO 5: Edge Cases")
    print("=" * 70)
    
    mapper = TypeMapper()
    
    edge_cases = [
        ("Empty values", []),
        ("All nulls", ["", "", "", ""]),
        ("Mixed types", ["123", "abc", "456", "def"]),
        ("Leading zeros", ["00501", "01234", "02345"]),
        ("Version numbers", ["1.2.3", "2.0.1", "3.14.159"]),
        ("Sparse integers", ["1", "2", "", "3", "", "4"]),
    ]
    
    for description, sample_values in edge_cases:
        data_type, confidence = mapper.infer_column_type("test_col", sample_values)
        print(f"\n{description:20} → {data_type.value:20} (Confidence: {confidence:.1%})")


def main():
    """Run all demos."""
    print("\n" + "=" * 70)
    print("TYPE MAPPER INTEGRATION DEMO")
    print("Intelligent Type Inference for Silver Layer Schema")
    print("=" * 70)
    
    demo_basic_type_inference()
    demo_confidence_strategies()
    demo_integer_size_selection()
    demo_schema_creation_from_bronze()
    demo_edge_cases()
    
    print("\n" + "=" * 70)
    print("DEMO COMPLETE")
    print("=" * 70)
    print("\nKey Features Demonstrated:")
    print("  ✓ Automatic type inference from string data")
    print("  ✓ Support for 20+ ClickHouse types")
    print("  ✓ Intelligent integer size selection")
    print("  ✓ Configurable confidence strategies")
    print("  ✓ Array type detection")
    print("  ✓ Edge case handling")
    print("  ✓ Integration with silver schema creation")
    print()


if __name__ == "__main__":
    main()
