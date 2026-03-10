"""
Type Mapping Utility for Silver Layer
Intelligently maps bronze String columns to proper ClickHouse types.

Based on design.md section 5.2 and requirements FR-2, US-6.
Implements intelligent type inference based on data patterns.
"""
import re
from typing import Any, Optional, List, Dict, Tuple
from datetime import datetime
from enum import Enum
import logging

# Add parent directory to path for imports
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from models.silver_schema import DataType
from .ch_identifiers import quote_columns, quote_table_name, sanitize_identifier_map

logger = logging.getLogger(__name__)


class TypeInferenceStrategy(str, Enum):
    """Strategy for type inference."""
    STRICT = "strict"  # Only infer if 100% confident
    LENIENT = "lenient"  # Infer with reasonable confidence
    CONSERVATIVE = "conservative"  # Default to String unless obvious


class TypeMapper:
    """
    Maps bronze String columns to proper silver layer types.
    
    Analyzes data patterns to intelligently infer appropriate ClickHouse types:
    - Int64, Float64 for numeric data
    - DateTime64 for timestamps
    - Bool for boolean values
    - Array types for list-like data
    - String as fallback
    """
    
    # Regex patterns for type detection
    INTEGER_PATTERN = re.compile(r'^-?\d+$')
    FLOAT_PATTERN = re.compile(r'^-?\d+\.\d+$')
    BOOLEAN_PATTERN = re.compile(r'^(true|false|yes|no|1|0|t|f|y|n)$', re.IGNORECASE)
    
    # ISO 8601 datetime patterns
    DATETIME_PATTERNS = [
        re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}'),  # ISO 8601
        re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}'),  # SQL format
        re.compile(r'^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}'),  # US format
    ]
    
    DATE_PATTERNS = [
        re.compile(r'^\d{4}-\d{2}-\d{2}$'),  # ISO date
        re.compile(r'^\d{2}/\d{2}/\d{4}$'),  # US date
    ]
    
    def __init__(self, strategy: TypeInferenceStrategy = TypeInferenceStrategy.CONSERVATIVE):
        """
        Initialize type mapper.
        
        Args:
            strategy: Type inference strategy (default: CONSERVATIVE)
        """
        self.strategy = strategy
    
    def infer_column_type(
        self,
        column_name: str,
        sample_values: List[str],
        null_count: int = 0
    ) -> Tuple[DataType, float]:
        """
        Infer the appropriate ClickHouse type for a column based on sample values.
        
        Args:
            column_name: Name of the column (used for heuristics)
            sample_values: List of sample string values from the column
            null_count: Number of null/empty values in the sample
        
        Returns:
            Tuple of (inferred DataType, confidence score 0.0-1.0)
        """
        if not sample_values:
            return DataType.STRING, 0.0
        
        # Filter out empty strings and None values
        non_empty_values = [v for v in sample_values if v and v.strip()]
        
        if not non_empty_values:
            return DataType.STRING, 0.0
        
        total_count = len(sample_values)
        valid_count = len(non_empty_values)
        
        # Try type inference in order of specificity
        
        # 1. Check for boolean
        bool_result = self._check_boolean(non_empty_values)
        if bool_result[0]:
            confidence = bool_result[1] * (valid_count / total_count)
            if self._meets_confidence_threshold(confidence):
                return DataType.BOOLEAN, confidence
        
        # 2. Check for integer
        int_result = self._check_integer(non_empty_values)
        if int_result[0]:
            confidence = int_result[1] * (valid_count / total_count)
            if self._meets_confidence_threshold(confidence):
                # Determine integer size based on column name heuristics
                return self._select_integer_type(column_name, non_empty_values), confidence
        
        # 3. Check for float
        float_result = self._check_float(non_empty_values)
        if float_result[0]:
            confidence = float_result[1] * (valid_count / total_count)
            if self._meets_confidence_threshold(confidence):
                return DataType.FLOAT64, confidence
        
        # 4. Check for datetime
        datetime_result = self._check_datetime(non_empty_values)
        if datetime_result[0]:
            confidence = datetime_result[1] * (valid_count / total_count)
            if self._meets_confidence_threshold(confidence):
                return DataType.DATETIME64, confidence
        
        # 5. Check for date
        date_result = self._check_date(non_empty_values)
        if date_result[0]:
            confidence = date_result[1] * (valid_count / total_count)
            if self._meets_confidence_threshold(confidence):
                return DataType.DATE, confidence
        
        # 6. Check for array (comma-separated values)
        array_result = self._check_array(non_empty_values)
        if array_result[0]:
            confidence = array_result[1] * (valid_count / total_count)
            if self._meets_confidence_threshold(confidence):
                return array_result[2], confidence  # Returns specific array type
        
        # Default to String
        return DataType.STRING, 1.0
    
    def _check_boolean(self, values: List[str]) -> Tuple[bool, float]:
        """
        Check if values are boolean.
        
        Returns:
            Tuple of (is_boolean, confidence)
        """
        matches = sum(1 for v in values if self.BOOLEAN_PATTERN.match(v.strip()))
        confidence = matches / len(values)
        
        return confidence > 0.95, confidence
    
    def _check_integer(self, values: List[str]) -> Tuple[bool, float]:
        """
        Check if values are integers.
        
        Returns:
            Tuple of (is_integer, confidence)
        """
        matches = 0
        for v in values:
            v_stripped = v.strip()
            if self.INTEGER_PATTERN.match(v_stripped):
                # Avoid treating leading zeros as integers (e.g., "007" should be string)
                if not (v_stripped.startswith('0') and len(v_stripped) > 1 and v_stripped != '0'):
                    matches += 1
        
        confidence = matches / len(values)
        
        return confidence > 0.95, confidence
    
    def _check_float(self, values: List[str]) -> Tuple[bool, float]:
        """
        Check if values are floats.
        
        Returns:
            Tuple of (is_float, confidence)
        """
        matches = 0
        for v in values:
            v_stripped = v.strip()
            if self.FLOAT_PATTERN.match(v_stripped):
                matches += 1
            elif self.INTEGER_PATTERN.match(v_stripped):
                # Integers can be represented as floats
                matches += 0.5
        
        confidence = matches / len(values)
        
        return confidence > 0.95, confidence
    
    def _check_datetime(self, values: List[str]) -> Tuple[bool, float]:
        """
        Check if values are datetimes.
        
        Returns:
            Tuple of (is_datetime, confidence)
        """
        matches = 0
        for v in values:
            v_stripped = v.strip()
            for pattern in self.DATETIME_PATTERNS:
                if pattern.match(v_stripped):
                    matches += 1
                    break
        
        confidence = matches / len(values)
        
        return confidence > 0.95, confidence
    
    def _check_date(self, values: List[str]) -> Tuple[bool, float]:
        """
        Check if values are dates.
        
        Returns:
            Tuple of (is_date, confidence)
        """
        matches = 0
        for v in values:
            v_stripped = v.strip()
            for pattern in self.DATE_PATTERNS:
                if pattern.match(v_stripped):
                    matches += 1
                    break
        
        confidence = matches / len(values)
        
        return confidence > 0.95, confidence
    
    def _check_array(self, values: List[str]) -> Tuple[bool, float, DataType]:
        """
        Check if values are arrays (comma-separated).
        
        Returns:
            Tuple of (is_array, confidence, array_type)
        """
        # Check if values contain commas (potential arrays)
        comma_count = sum(1 for v in values if ',' in v)
        
        if comma_count / len(values) < 0.8:
            return False, 0.0, DataType.STRING
        
        # Analyze array element types
        all_elements = []
        for v in values:
            elements = [e.strip() for e in v.split(',')]
            all_elements.extend(elements)
        
        if not all_elements:
            return False, 0.0, DataType.STRING
        
        # Check if array elements are integers
        int_result = self._check_integer(all_elements)
        if int_result[0]:
            return True, int_result[1], DataType.ARRAY_INT64
        
        # Check if array elements are floats
        float_result = self._check_float(all_elements)
        if float_result[0]:
            return True, float_result[1], DataType.ARRAY_FLOAT64
        
        # Default to string array
        return True, 0.9, DataType.ARRAY_STRING
    
    def _select_integer_type(self, column_name: str, values: List[str]) -> DataType:
        """
        Select appropriate integer type based on column name and value range.
        
        Args:
            column_name: Name of the column
            values: Sample integer values
        
        Returns:
            Appropriate integer DataType
        """
        # Check for ID columns (typically unsigned)
        if '_id' in column_name.lower() or column_name.lower().endswith('id'):
            # Check if all values are non-negative
            try:
                int_values = [int(v.strip()) for v in values]
                if all(v >= 0 for v in int_values):
                    max_val = max(int_values)
                    
                    if max_val < 2**8:
                        return DataType.UINT8
                    elif max_val < 2**16:
                        return DataType.UINT16
                    elif max_val < 2**32:
                        return DataType.UINT32
                    else:
                        return DataType.UINT64
            except (ValueError, OverflowError):
                pass
        
        # For signed integers, check range
        try:
            int_values = [int(v.strip()) for v in values]
            min_val = min(int_values)
            max_val = max(int_values)
            
            if -2**7 <= min_val and max_val < 2**7:
                return DataType.INT8
            elif -2**15 <= min_val and max_val < 2**15:
                return DataType.INT16
            elif -2**31 <= min_val and max_val < 2**31:
                return DataType.INT32
            else:
                return DataType.INT64
        except (ValueError, OverflowError):
            pass
        
        # Default to Int64
        return DataType.INT64
    
    def _meets_confidence_threshold(self, confidence: float) -> bool:
        """
        Check if confidence meets threshold for the current strategy.
        
        Args:
            confidence: Confidence score (0.0-1.0)
        
        Returns:
            True if confidence meets threshold
        """
        if self.strategy == TypeInferenceStrategy.STRICT:
            return confidence >= 0.99
        elif self.strategy == TypeInferenceStrategy.LENIENT:
            return confidence >= 0.90
        else:  # CONSERVATIVE
            return confidence >= 0.95
    
    def infer_schema_from_bronze(
        self,
        bronze_table_name: str,
        sample_size: int = 1000,
        clickhouse_client = None
    ) -> Dict[str, Tuple[DataType, float]]:
        """
        Infer silver schema from bronze table by analyzing sample data.
        
        Args:
            bronze_table_name: Name of the bronze table
            sample_size: Number of rows to sample for type inference
            clickhouse_client: ClickHouse client instance
        
        Returns:
            Dictionary mapping column names to (DataType, confidence) tuples
        """
        if not clickhouse_client:
            raise ValueError("ClickHouse client is required for schema inference")
        
        try:
            # Get bronze table columns (excluding lineage/metadata columns)
            safe_table = quote_table_name(bronze_table_name)
            describe_query = f"DESCRIBE TABLE {safe_table}"
            columns_result = clickhouse_client.execute(describe_query)

            raw_columns = [
                str(col[0]) for col in columns_result
                if not str(col[0]).startswith('_')  # Exclude lineage columns
            ]
            column_mapping = sanitize_identifier_map(raw_columns, prefix="c", fallback="column")
            data_columns = [column_mapping[col] for col in raw_columns]
            
            if not data_columns:
                logger.warning(f"No data columns found in {bronze_table_name}")
                return {}
            
            # Sample data from bronze table
            sample_query = f"""
                SELECT {quote_columns(data_columns)}
                FROM {safe_table}
                LIMIT {sample_size}
            """
            
            sample_data = clickhouse_client.execute(sample_query)
            
            if not sample_data:
                logger.warning(f"No sample data found in {bronze_table_name}")
                return {}
            
            # Infer type for each column
            schema_mapping = {}
            
            for col_idx, col_name in enumerate(data_columns):
                # Extract column values from sample
                col_values = [str(row[col_idx]) if row[col_idx] is not None else '' for row in sample_data]
                
                # Count nulls
                null_count = sum(1 for v in col_values if not v or v == 'None')
                
                # Infer type
                inferred_type, confidence = self.infer_column_type(
                    col_name,
                    col_values,
                    null_count
                )
                
                schema_mapping[col_name] = (inferred_type, confidence)
                
                logger.info(
                    f"Column '{col_name}': {inferred_type.value} "
                    f"(confidence: {confidence:.2%})"
                )
            
            return schema_mapping
            
        except Exception as e:
            logger.error(f"Error inferring schema from bronze table: {e}")
            raise


def create_silver_schema_from_bronze(
    source_name: str,
    bronze_table_name: str,
    clickhouse_client,
    strategy: TypeInferenceStrategy = TypeInferenceStrategy.CONSERVATIVE,
    sample_size: int = 1000
):
    """
    Create a SilverTableSchema by inferring types from a bronze table.
    
    Args:
        source_name: Name of the data source
        bronze_table_name: Name of the bronze table to analyze
        clickhouse_client: ClickHouse client instance
        strategy: Type inference strategy
        sample_size: Number of rows to sample
    
    Returns:
        SilverTableSchema with inferred column types
    """
    from models.silver_schema import SilverTableSchema, SilverColumnDefinition
    
    # Initialize type mapper
    mapper = TypeMapper(strategy=strategy)
    
    # Infer schema
    schema_mapping = mapper.infer_schema_from_bronze(
        bronze_table_name,
        sample_size,
        clickhouse_client
    )
    
    # Create silver column definitions
    data_columns = []
    for col_name, (data_type, confidence) in schema_mapping.items():
        # Determine if column should be nullable based on confidence
        nullable = confidence < 0.99
        
        column = SilverColumnDefinition(
            name=col_name,
            data_type=data_type,
            nullable=nullable,
            comment=f"Inferred type with {confidence:.1%} confidence"
        )
        data_columns.append(column)
    
    # Create silver schema
    schema = SilverTableSchema(
        source_name=source_name,
        data_columns=data_columns
    )
    
    return schema
