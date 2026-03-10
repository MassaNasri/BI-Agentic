"""
Schema Validator - Validates data against schema contracts.

This module provides the SchemaValidator class which validates data rows
against SchemaContract definitions. It supports:
- Single row validation
- Batch validation
- Schema caching for performance
- Detailed validation reporting

Based on design.md section 3.2 and requirements FR-4, FR-5, US-4.
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import logging

from .schema_contract import SchemaContract, ValidationResult


logger = logging.getLogger(__name__)


@dataclass
class BatchValidationResult:
    """
    Result of batch validation.
    
    Attributes:
        total_rows: Total number of rows validated
        valid_rows: Number of valid rows
        invalid_rows: Number of invalid rows
        validation_results: List of ValidationResult for each row
        overall_quality_score: Average quality score across all rows
        validated_at: When validation was performed
        schema_id: ID of schema used for validation
        schema_version: Version of schema used for validation
    """
    total_rows: int
    valid_rows: int
    invalid_rows: int
    validation_results: List[ValidationResult]
    overall_quality_score: float = 0.0
    validated_at: datetime = field(default_factory=datetime.utcnow)
    schema_id: str = ""
    schema_version: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "total_rows": self.total_rows,
            "valid_rows": self.valid_rows,
            "invalid_rows": self.invalid_rows,
            "overall_quality_score": self.overall_quality_score,
            "validated_at": self.validated_at.isoformat(),
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "validation_results": [r.to_dict() for r in self.validation_results]
        }


class SchemaValidator:
    """
    Validates data against schema contracts.
    
    This class provides validation services for the ETL pipeline, ensuring
    data conforms to defined schema contracts. It supports both single-row
    and batch validation with performance optimizations.
    
    Features:
    - Single row validation
    - Batch validation with aggregated results
    - Schema caching for performance
    - Detailed error reporting
    - Quality score calculation
    
    Example:
        validator = SchemaValidator()
        
        # Single row validation
        result = validator.validate(row, schema_contract)
        if not result.is_valid:
            print(f"Validation errors: {result.violations}")
        
        # Batch validation
        batch_result = validator.validate_batch(rows, schema_contract)
        print(f"Valid: {batch_result.valid_rows}/{batch_result.total_rows}")
    """
    
    def __init__(self, cache_schemas: bool = True):
        """
        Initialize the SchemaValidator.
        
        Args:
            cache_schemas: Whether to cache schema contracts for performance
        """
        self.cache_schemas = cache_schemas
        self._schema_cache: Dict[str, SchemaContract] = {}
        logger.info("SchemaValidator initialized with caching=%s", cache_schemas)
    
    def validate(
        self,
        row: Dict[str, Any],
        schema_contract: SchemaContract
    ) -> ValidationResult:
        """
        Validate a single row against a schema contract.
        
        This method validates a data row against the provided schema contract,
        checking types, constraints, and required fields.
        
        Args:
            row: Dictionary representing a data row
            schema_contract: SchemaContract to validate against
            
        Returns:
            ValidationResult containing validation status and details
            
        Example:
            schema = SchemaContract(
                schema_id="user_schema",
                version="1.0.0",
                fields=[
                    FieldDefinition(name="id", type=DataType.INTEGER, nullable=False),
                    FieldDefinition(name="email", type=DataType.STRING, nullable=False)
                ]
            )
            
            row = {"id": 1, "email": "user@example.com"}
            result = validator.validate(row, schema)
            
            if result.is_valid:
                print(f"Quality score: {result.quality_score}")
            else:
                print(f"Errors: {result.violations}")
        """
        logger.debug(
            "Validating row against schema %s v%s",
            schema_contract.schema_id,
            schema_contract.version
        )
        
        # Use the SchemaContract's built-in validation
        result = schema_contract.validate_row(row)
        
        # Log validation result
        if not result.is_valid:
            logger.warning(
                "Row validation failed for schema %s: %d violations",
                schema_contract.schema_id,
                len(result.violations)
            )
        
        return result
    
    def validate_batch(
        self,
        rows: List[Dict[str, Any]],
        schema_contract: SchemaContract,
        stop_on_first_error: bool = False
    ) -> BatchValidationResult:
        """
        Validate a batch of rows against a schema contract.
        
        This method validates multiple rows and provides aggregated results
        including overall quality scores and detailed per-row results.
        
        Args:
            rows: List of dictionaries representing data rows
            schema_contract: SchemaContract to validate against
            stop_on_first_error: If True, stop validation on first error
            
        Returns:
            BatchValidationResult with aggregated validation results
            
        Example:
            rows = [
                {"id": 1, "email": "user1@example.com"},
                {"id": 2, "email": "user2@example.com"},
                {"id": 3, "email": "invalid-email"}
            ]
            
            result = validator.validate_batch(rows, schema)
            print(f"Valid: {result.valid_rows}/{result.total_rows}")
            print(f"Overall quality: {result.overall_quality_score:.2%}")
            
            # Check individual results
            for i, validation in enumerate(result.validation_results):
                if not validation.is_valid:
                    print(f"Row {i} errors: {validation.violations}")
        """
        logger.info(
            "Validating batch of %d rows against schema %s v%s",
            len(rows),
            schema_contract.schema_id,
            schema_contract.version
        )
        
        validation_results = []
        valid_count = 0
        invalid_count = 0
        total_quality_score = 0.0
        
        for i, row in enumerate(rows):
            result = self.validate(row, schema_contract)
            validation_results.append(result)
            
            if result.is_valid:
                valid_count += 1
            else:
                invalid_count += 1
                
                if stop_on_first_error:
                    logger.warning(
                        "Stopping batch validation at row %d due to error",
                        i
                    )
                    break
            
            total_quality_score += result.quality_score
        
        # Calculate overall quality score
        overall_quality_score = (
            total_quality_score / len(validation_results)
            if validation_results else 0.0
        )
        
        batch_result = BatchValidationResult(
            total_rows=len(rows),
            valid_rows=valid_count,
            invalid_rows=invalid_count,
            validation_results=validation_results,
            overall_quality_score=overall_quality_score,
            schema_id=schema_contract.schema_id,
            schema_version=schema_contract.version
        )
        
        logger.info(
            "Batch validation complete: %d/%d valid (%.2f%% quality)",
            valid_count,
            len(rows),
            overall_quality_score * 100
        )
        
        return batch_result
    
    def get_invalid_rows(
        self,
        rows: List[Dict[str, Any]],
        schema_contract: SchemaContract
    ) -> List[tuple[int, Dict[str, Any], ValidationResult]]:
        """
        Get all invalid rows from a batch with their validation results.
        
        This is a convenience method for filtering out invalid rows,
        useful for quarantine operations.
        
        Args:
            rows: List of dictionaries representing data rows
            schema_contract: SchemaContract to validate against
            
        Returns:
            List of tuples (row_index, row_data, validation_result)
            for all invalid rows
            
        Example:
            invalid_rows = validator.get_invalid_rows(rows, schema)
            
            for idx, row, result in invalid_rows:
                print(f"Row {idx} failed: {result.violations}")
                # Quarantine the row
                quarantine_manager.quarantine(row, result.violations)
        """
        logger.debug("Filtering invalid rows from batch of %d", len(rows))
        
        invalid_rows = []
        
        for i, row in enumerate(rows):
            result = self.validate(row, schema_contract)
            if not result.is_valid:
                invalid_rows.append((i, row, result))
        
        logger.info("Found %d invalid rows out of %d", len(invalid_rows), len(rows))
        
        return invalid_rows
    
    def get_valid_rows(
        self,
        rows: List[Dict[str, Any]],
        schema_contract: SchemaContract
    ) -> List[tuple[int, Dict[str, Any], ValidationResult]]:
        """
        Get all valid rows from a batch with their validation results.
        
        This is a convenience method for filtering out valid rows,
        useful for processing only clean data.
        
        Args:
            rows: List of dictionaries representing data rows
            schema_contract: SchemaContract to validate against
            
        Returns:
            List of tuples (row_index, row_data, validation_result)
            for all valid rows
            
        Example:
            valid_rows = validator.get_valid_rows(rows, schema)
            
            for idx, row, result in valid_rows:
                print(f"Row {idx} quality: {result.quality_score:.2%}")
                # Process the valid row
                process_row(row)
        """
        logger.debug("Filtering valid rows from batch of %d", len(rows))
        
        valid_rows = []
        
        for i, row in enumerate(rows):
            result = self.validate(row, schema_contract)
            if result.is_valid:
                valid_rows.append((i, row, result))
        
        logger.info("Found %d valid rows out of %d", len(valid_rows), len(rows))
        
        return valid_rows
    
    def cache_schema(self, schema_contract: SchemaContract) -> None:
        """
        Cache a schema contract for faster repeated validation.
        
        Args:
            schema_contract: SchemaContract to cache
        """
        if not self.cache_schemas:
            return
        
        cache_key = f"{schema_contract.schema_id}:{schema_contract.version}"
        self._schema_cache[cache_key] = schema_contract
        
        logger.debug("Cached schema %s", cache_key)
    
    def get_cached_schema(
        self,
        schema_id: str,
        version: str
    ) -> Optional[SchemaContract]:
        """
        Retrieve a cached schema contract.
        
        Args:
            schema_id: Schema identifier
            version: Schema version
            
        Returns:
            Cached SchemaContract or None if not found
        """
        if not self.cache_schemas:
            return None
        
        cache_key = f"{schema_id}:{version}"
        return self._schema_cache.get(cache_key)
    
    def clear_cache(self) -> None:
        """Clear all cached schema contracts."""
        self._schema_cache.clear()
        logger.info("Schema cache cleared")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        return {
            "enabled": self.cache_schemas,
            "cached_schemas": len(self._schema_cache),
            "schema_keys": list(self._schema_cache.keys())
        }
