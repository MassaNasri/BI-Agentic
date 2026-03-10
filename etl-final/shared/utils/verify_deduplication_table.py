"""
Verification script for deduplication_log table implementation.
This script verifies that the table schema matches the design specification.
"""
import sys
from clickhouse_schemas import ClickHouseSchemaManager


def verify_schema_implementation():
    """
    Verify that the deduplication_log table implementation matches the design spec.
    
    Design specification (from design.md section 5.4):
    - _dedup_key: String (SHA256 hash for deduplication)
    - _batch_id: String (Batch identifier)
    - _stage: String (Pipeline stage: extract, transform, load)
    - _processed_at: DateTime64(3) (Processing timestamp)
    - _row_id: UUID (UUID of the processed row)
    - ENGINE: ReplacingMergeTree(_processed_at)
    - PARTITION BY: toYYYYMM(_processed_at)
    - ORDER BY: (_dedup_key, _stage)
    """
    print("=" * 70)
    print("DEDUPLICATION_LOG TABLE VERIFICATION")
    print("=" * 70)
    print()
    
    # Expected schema from design.md
    expected_schema = {
        '_dedup_key': 'String',
        '_batch_id': 'String',
        '_stage': 'String',
        '_processed_at': 'DateTime64(3)',
        '_row_id': 'UUID'
    }
    
    expected_engine = 'ReplacingMergeTree'
    expected_partition = 'toYYYYMM(_processed_at)'
    expected_order = '(_dedup_key, _stage)'
    
    print("✓ Expected Schema:")
    for col, dtype in expected_schema.items():
        print(f"  - {col}: {dtype}")
    print()
    
    print("✓ Expected Engine: ReplacingMergeTree(_processed_at)")
    print("✓ Expected Partition: PARTITION BY toYYYYMM(_processed_at)")
    print("✓ Expected Order: ORDER BY (_dedup_key, _stage)")
    print()
    
    # Verify the SQL query in the implementation
    print("=" * 70)
    print("IMPLEMENTATION VERIFICATION")
    print("=" * 70)
    print()
    
    # Read the implementation
    import inspect
    source = inspect.getsource(ClickHouseSchemaManager.create_deduplication_log_table)
    
    # Check for required elements
    checks = {
        'CREATE TABLE IF NOT EXISTS deduplication_log': False,
        '_dedup_key String': False,
        '_batch_id String': False,
        '_stage String': False,
        '_processed_at DateTime64(3)': False,
        '_row_id UUID': False,
        'ENGINE = ReplacingMergeTree(_processed_at)': False,
        'PARTITION BY toYYYYMM(_processed_at)': False,
        'ORDER BY (_dedup_key, _stage)': False
    }
    
    for check in checks:
        if check in source:
            checks[check] = True
    
    all_passed = True
    for check, passed in checks.items():
        status = "✓" if passed else "✗"
        print(f"{status} {check}")
        if not passed:
            all_passed = False
    
    print()
    print("=" * 70)
    if all_passed:
        print("✓ ALL CHECKS PASSED - Implementation matches design specification")
        print("=" * 70)
        return True
    else:
        print("✗ SOME CHECKS FAILED - Implementation does not match design")
        print("=" * 70)
        return False


def print_implementation_details():
    """Print the actual implementation for review."""
    print()
    print("=" * 70)
    print("ACTUAL IMPLEMENTATION")
    print("=" * 70)
    print()
    
    import inspect
    source = inspect.getsource(ClickHouseSchemaManager.create_deduplication_log_table)
    print(source)


if __name__ == '__main__':
    success = verify_schema_implementation()
    print_implementation_details()
    
    sys.exit(0 if success else 1)
