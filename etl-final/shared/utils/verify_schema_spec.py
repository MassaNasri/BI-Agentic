"""
Verification script for deduplication_log table implementation.
Verifies the SQL schema matches the design specification without requiring dependencies.
"""
import re


def verify_schema():
    """Verify the deduplication_log table schema matches design.md section 5.4."""
    
    print("=" * 70)
    print("DEDUPLICATION_LOG TABLE VERIFICATION")
    print("=" * 70)
    print()
    
    # Read the implementation file
    with open('clickhouse_schemas.py', 'r') as f:
        content = f.read()
    
    # Extract the CREATE TABLE query
    match = re.search(
        r'create_query = """(.*?)"""',
        content,
        re.DOTALL
    )
    
    if not match:
        print("✗ Could not find CREATE TABLE query in implementation")
        return False
    
    create_query = match.group(1).strip()
    
    print("Found CREATE TABLE query:")
    print("-" * 70)
    print(create_query)
    print("-" * 70)
    print()
    
    # Expected elements from design.md section 5.4
    required_elements = {
        'Table name': 'deduplication_log',
        'Column: _dedup_key': '_dedup_key String',
        'Column: _batch_id': '_batch_id String',
        'Column: _stage': '_stage String',
        'Column: _processed_at': '_processed_at DateTime64(3)',
        'Column: _row_id': '_row_id UUID',
        'Engine': 'ReplacingMergeTree(_processed_at)',
        'Partition': 'PARTITION BY toYYYYMM(_processed_at)',
        'Order': 'ORDER BY (_dedup_key, _stage)'
    }
    
    print("Verification Results:")
    print("-" * 70)
    
    all_passed = True
    for name, expected in required_elements.items():
        if expected in create_query:
            print(f"✓ {name}: {expected}")
        else:
            print(f"✗ {name}: {expected} - NOT FOUND")
            all_passed = False
    
    print("-" * 70)
    print()
    
    if all_passed:
        print("=" * 70)
        print("✓ SUCCESS: Implementation matches design specification!")
        print("=" * 70)
        print()
        print("The deduplication_log table includes:")
        print("  • All required columns with correct types")
        print("  • ReplacingMergeTree engine for automatic deduplication")
        print("  • Monthly partitioning for efficient data management")
        print("  • Proper ordering by (_dedup_key, _stage) for deduplication")
        print()
        return True
    else:
        print("=" * 70)
        print("✗ FAILURE: Implementation does not match specification")
        print("=" * 70)
        return False


if __name__ == '__main__':
    import sys
    success = verify_schema()
    sys.exit(0 if success else 1)
