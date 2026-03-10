"""
Quick test to verify quality score columns are in the SQL output.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'shared'))

from models.silver_schema import SilverTableSchema, SilverColumnDefinition, DataType

# Create a simple schema
schema = SilverTableSchema(
    source_name='test_table',
    data_columns=[
        SilverColumnDefinition('customer_id', DataType.INT64, comment='Customer ID'),
        SilverColumnDefinition('name', DataType.STRING, comment='Customer name'),
        SilverColumnDefinition('email', DataType.STRING, nullable=True, comment='Email address')
    ]
)

# Generate SQL
sql = schema.get_create_table_sql()

print("=" * 80)
print("SILVER TABLE SQL WITH QUALITY SCORE COLUMNS")
print("=" * 80)
print(sql)
print("\n" + "=" * 80)
print("VERIFICATION")
print("=" * 80)

# Verify quality columns are present
quality_columns = [
    '_quality_score Float32',
    '_applied_rules Array(String)',
    '_warnings Array(String)',
    '_completeness_score Float32',
    '_validity_score Float32'
]

print("\nChecking for quality score columns:")
for col in quality_columns:
    if col in sql:
        print(f"  ✓ {col}")
    else:
        print(f"  ✗ {col} - MISSING!")

print("\n" + "=" * 80)
