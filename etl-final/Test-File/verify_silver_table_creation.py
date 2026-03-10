"""
Verification script for task 3.2.2: Silver table creation scripts
Validates that the implementation meets all requirements.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'shared'))

from models.silver_schema import (
    SilverTableSchema,
    SilverColumnDefinition,
    DataType
)

def verify_requirements():
    """Verify all requirements for task 3.2.2."""
    print("=" * 70)
    print("TASK 3.2.2 VERIFICATION: Silver Table Creation Scripts")
    print("=" * 70)
    
    # Create a test schema with various data types
    schema = SilverTableSchema(
        source_name="test_customers",
        data_columns=[
            SilverColumnDefinition(
                name="customer_id",
                data_type=DataType.INT64,
                nullable=False,
                comment="Customer identifier"
            ),
            SilverColumnDefinition(
                name="email",
                data_type=DataType.STRING,
                nullable=False,
                comment="Customer email"
            ),
            SilverColumnDefinition(
                name="age",
                data_type=DataType.INT32,
                nullable=True,
                comment="Customer age"
            ),
            SilverColumnDefinition(
                name="balance",
                data_type=DataType.FLOAT64,
                nullable=True,
                comment="Account balance"
            ),
            SilverColumnDefinition(
                name="is_active",
                data_type=DataType.BOOLEAN,
                nullable=False,
                default_value="true",
                comment="Active status"
            ),
            SilverColumnDefinition(
                name="registration_date",
                data_type=DataType.DATE,
                nullable=False,
                comment="Registration date"
            ),
            SilverColumnDefinition(
                name="last_login",
                data_type=DataType.DATETIME64,
                nullable=True,
                comment="Last login timestamp"
            )
        ]
    )
    
    # Generate SQL
    sql = schema.get_create_table_sql()
    
    print("\n✓ Generated SQL for silver table:")
    print("-" * 70)
    print(sql)
    print("-" * 70)
    
    # Verify requirements
    requirements = {
        "✓ Proper type mapping (not all String)": [
            "Int64" in sql,
            "Int32" in sql,
            "Float64" in sql,
            "Bool" in sql,
            "Date" in sql,
            "DateTime64" in sql
        ],
        "✓ Quality metadata columns": [
            "_quality_score Float32" in sql,
            "_applied_rules Array(String)" in sql,
            "_warnings Array(String)" in sql,
            "_completeness_score Float32" in sql,
            "_validity_score Float32" in sql
        ],
        "✓ Lineage columns": [
            "_row_id UUID" in sql,
            "_bronze_row_id UUID" in sql,
            "_batch_id String" in sql,
            "_cleaned_at DateTime64(3)" in sql,
            "_cleaning_version String" in sql
        ],
        "✓ Partitioning by date": [
            "PARTITION BY" in sql,
            "toYYYYMM(_cleaned_at)" in sql
        ],
        "✓ Appropriate indexes": [
            "INDEX idx_bronze_row_id" in sql,
            "INDEX idx_quality_score" in sql,
            "INDEX idx_cleaned_at" in sql
        ],
        "✓ MergeTree engine": [
            "ENGINE = MergeTree()" in sql
        ],
        "✓ Ordering columns": [
            "ORDER BY" in sql,
            "_batch_id" in sql,
            "_row_id" in sql
        ],
        "✓ Nullable support": [
            "Nullable(Int32)" in sql,
            "Nullable(Float64)" in sql,
            "Nullable(DateTime64(3))" in sql
        ],
        "✓ Default values": [
            "DEFAULT" in sql
        ],
        "✓ Column comments": [
            "COMMENT" in sql
        ]
    }
    
    print("\n" + "=" * 70)
    print("REQUIREMENT VERIFICATION")
    print("=" * 70)
    
    all_passed = True
    for requirement, checks in requirements.items():
        passed = all(checks)
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status} - {requirement}")
        if not passed:
            all_passed = False
            print(f"  Failed checks: {[i for i, c in enumerate(checks) if not c]}")
    
    print("\n" + "=" * 70)
    if all_passed:
        print("✓ ALL REQUIREMENTS MET")
    else:
        print("✗ SOME REQUIREMENTS FAILED")
    print("=" * 70)
    
    return all_passed


if __name__ == "__main__":
    success = verify_requirements()
    sys.exit(0 if success else 1)
