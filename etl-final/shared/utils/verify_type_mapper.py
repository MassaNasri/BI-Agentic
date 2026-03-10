"""
Verification script for Type Mapper functionality.
Runs comprehensive tests to verify type inference works correctly.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.type_mapper import TypeMapper, TypeInferenceStrategy
from models.silver_schema import DataType


def test_integer_inference():
    """Test integer type inference."""
    mapper = TypeMapper()
    
    int_values = ["1", "2", "3", "42", "100"]
    data_type, confidence = mapper.infer_column_type("count", int_values)
    
    # Should select INT8 since all values fit in Int8 range (-128 to 127)
    assert data_type == DataType.INT8, f"Expected INT8, got {data_type}"
    assert confidence > 0.95, f"Expected confidence > 0.95, got {confidence}"
    print("✓ Integer inference test passed")


def test_float_inference():
    """Test float type inference."""
    mapper = TypeMapper()
    
    float_values = ["1.5", "2.7", "3.14", "42.0", "100.99"]
    data_type, confidence = mapper.infer_column_type("price", float_values)
    
    assert data_type == DataType.FLOAT64, f"Expected FLOAT64, got {data_type}"
    assert confidence > 0.95, f"Expected confidence > 0.95, got {confidence}"
    print("✓ Float inference test passed")


def test_boolean_inference():
    """Test boolean type inference."""
    mapper = TypeMapper()
    
    bool_values = ["true", "false", "true", "true", "false"]
    data_type, confidence = mapper.infer_column_type("is_active", bool_values)
    
    assert data_type == DataType.BOOLEAN, f"Expected BOOLEAN, got {data_type}"
    assert confidence > 0.95, f"Expected confidence > 0.95, got {confidence}"
    print("✓ Boolean inference test passed")


def test_datetime_inference():
    """Test datetime type inference."""
    mapper = TypeMapper()
    
    datetime_values = [
        "2024-01-15T10:30:00",
        "2024-02-20T14:45:30",
        "2024-03-10T08:15:45"
    ]
    data_type, confidence = mapper.infer_column_type("created_at", datetime_values)
    
    assert data_type == DataType.DATETIME64, f"Expected DATETIME64, got {data_type}"
    assert confidence > 0.95, f"Expected confidence > 0.95, got {confidence}"
    print("✓ Datetime inference test passed")


def test_date_inference():
    """Test date type inference."""
    mapper = TypeMapper()
    
    date_values = ["2024-01-15", "2024-02-20", "2024-03-10"]
    data_type, confidence = mapper.infer_column_type("birth_date", date_values)
    
    assert data_type == DataType.DATE, f"Expected DATE, got {data_type}"
    assert confidence > 0.95, f"Expected confidence > 0.95, got {confidence}"
    print("✓ Date inference test passed")


def test_unsigned_integer_inference():
    """Test unsigned integer inference for ID columns."""
    mapper = TypeMapper()
    
    small_ids = ["1", "2", "3", "10", "50"]
    data_type, confidence = mapper.infer_column_type("user_id", small_ids)
    
    assert data_type == DataType.UINT8, f"Expected UINT8, got {data_type}"
    assert confidence > 0.95, f"Expected confidence > 0.95, got {confidence}"
    print("✓ Unsigned integer inference test passed")


def test_array_inference():
    """Test array type inference."""
    mapper = TypeMapper()
    
    array_values = ["1,2,3", "4,5,6", "7,8,9", "10,11,12"]
    data_type, confidence = mapper.infer_column_type("tags", array_values)
    
    assert data_type == DataType.ARRAY_INT64, f"Expected ARRAY_INT64, got {data_type}"
    assert confidence > 0.8, f"Expected confidence > 0.8, got {confidence}"
    print("✓ Array inference test passed")


def test_leading_zeros_preserved():
    """Test that leading zeros are preserved as strings."""
    mapper = TypeMapper()
    
    zip_values = ["00501", "01234", "02345", "03456"]
    data_type, confidence = mapper.infer_column_type("zip_code", zip_values)
    
    assert data_type == DataType.STRING, f"Expected STRING for leading zeros, got {data_type}"
    print("✓ Leading zeros preservation test passed")


def test_mixed_types_default_to_string():
    """Test that mixed types default to string."""
    mapper = TypeMapper()
    
    mixed_values = ["123", "abc", "456", "def", "789"]
    data_type, confidence = mapper.infer_column_type("mixed_col", mixed_values)
    
    assert data_type == DataType.STRING, f"Expected STRING for mixed types, got {data_type}"
    print("✓ Mixed types test passed")


def test_confidence_strategies():
    """Test different confidence strategies."""
    # Strict strategy - need less than 99% to fail
    mapper_strict = TypeMapper(strategy=TypeInferenceStrategy.STRICT)
    mostly_int_values = ["1", "2", "3", "4", "5"] * 19 + ["abc"] * 2  # 95/97 = 97.9%
    data_type, confidence = mapper_strict.infer_column_type("col", mostly_int_values)
    assert data_type == DataType.STRING, f"Strict strategy should default to STRING, got {data_type}"
    print("✓ Strict strategy test passed")
    
    # Lenient strategy - still needs 95% match in _check_integer
    # The strategy threshold only applies AFTER the type check passes
    mapper_lenient = TypeMapper(strategy=TypeInferenceStrategy.LENIENT)
    mostly_int_values = ["1", "2", "3", "4", "5"] * 20 + ["abc"]  # 100/101 = 99%
    data_type, confidence = mapper_lenient.infer_column_type("col", mostly_int_values)
    # Should infer some integer type (INT8, INT16, INT32, or INT64)
    assert data_type in [DataType.INT8, DataType.INT16, DataType.INT32, DataType.INT64], f"Lenient strategy should infer integer type, got {data_type}"
    print("✓ Lenient strategy test passed")
    
    # Conservative strategy (default)
    mapper_conservative = TypeMapper(strategy=TypeInferenceStrategy.CONSERVATIVE)
    mostly_int_values = ["1", "2", "3", "4", "5"] * 20 + ["abc"]  # 100/101 = 99%
    data_type, confidence = mapper_conservative.infer_column_type("col", mostly_int_values)
    assert data_type in [DataType.INT8, DataType.INT16, DataType.INT32, DataType.INT64], f"Conservative strategy should infer integer type, got {data_type}"
    print("✓ Conservative strategy test passed")


def test_integer_size_selection():
    """Test selection of appropriate integer sizes."""
    mapper = TypeMapper()
    
    # Int8
    small_int_values = ["-10", "0", "10", "50", "100"]
    data_type, confidence = mapper.infer_column_type("small_num", small_int_values)
    assert data_type == DataType.INT8, f"Expected INT8, got {data_type}"
    print("✓ Int8 size selection test passed")
    
    # Int16
    medium_int_values = ["-1000", "0", "1000", "5000", "10000"]
    data_type, confidence = mapper.infer_column_type("medium_num", medium_int_values)
    assert data_type == DataType.INT16, f"Expected INT16, got {data_type}"
    print("✓ Int16 size selection test passed")
    
    # Int32
    large_int_values = ["-100000", "0", "100000", "500000", "1000000"]
    data_type, confidence = mapper.infer_column_type("large_num", large_int_values)
    assert data_type == DataType.INT32, f"Expected INT32, got {data_type}"
    print("✓ Int32 size selection test passed")


def main():
    """Run all verification tests."""
    print("=" * 60)
    print("Type Mapper Verification Tests")
    print("=" * 60)
    
    try:
        test_integer_inference()
        test_float_inference()
        test_boolean_inference()
        test_datetime_inference()
        test_date_inference()
        test_unsigned_integer_inference()
        test_array_inference()
        test_leading_zeros_preserved()
        test_mixed_types_default_to_string()
        test_confidence_strategies()
        test_integer_size_selection()
        
        print("=" * 60)
        print("✓ ALL TESTS PASSED!")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
