"""
Quality Score Calculator
Implements comprehensive quality scoring for silver layer data.

This module provides detailed quality score calculation based on:
- Completeness: Percentage of non-null required fields
- Validity: Percentage of fields passing validation rules
- Overall Quality: Weighted combination of completeness and validity

Based on design.md section 5.2 and requirements US-7 (Data Quality Metrics).
"""
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass
from enum import Enum


class ValidationSeverity(str, Enum):
    """Severity levels for validation issues."""
    ERROR = "error"  # Critical issue, affects validity score
    WARNING = "warning"  # Non-critical issue, logged but doesn't affect score
    INFO = "info"  # Informational, no impact on score


@dataclass
class ValidationIssue:
    """
    Represents a validation issue found during quality assessment.
    
    Attributes:
        field_name: Name of the field with the issue
        severity: Severity level of the issue
        message: Description of the issue
        rule_id: ID of the rule that detected the issue (if applicable)
    """
    field_name: str
    severity: ValidationSeverity
    message: str
    rule_id: Optional[str] = None


@dataclass
class QualityScoreResult:
    """
    Result of quality score calculation.
    
    Attributes:
        completeness_score: Score for data completeness (0.0 to 1.0)
        validity_score: Score for data validity (0.0 to 1.0)
        overall_score: Weighted overall quality score (0.0 to 1.0)
        issues: List of validation issues found
        applied_rules: List of rule IDs that were applied
        warnings: List of warning messages
    """
    completeness_score: float
    validity_score: float
    overall_score: float
    issues: List[ValidationIssue]
    applied_rules: List[str]
    warnings: List[str]


class QualityScoreCalculator:
    """
    Calculates quality scores for data rows.
    
    Provides methods to assess data completeness, validity, and overall quality
    based on schema definitions and validation rules.
    """
    
    def __init__(
        self,
        completeness_weight: float = 0.4,
        validity_weight: float = 0.6
    ):
        """
        Initialize quality score calculator.
        
        Args:
            completeness_weight: Weight for completeness score (default 0.4)
            validity_weight: Weight for validity score (default 0.6)
        
        Raises:
            ValueError: If weights don't sum to 1.0
        """
        if abs(completeness_weight + validity_weight - 1.0) > 0.001:
            raise ValueError(
                f"Weights must sum to 1.0, got {completeness_weight + validity_weight}"
            )
        
        self.completeness_weight = completeness_weight
        self.validity_weight = validity_weight
    
    def calculate_quality_score(
        self,
        row: Dict[str, Any],
        required_fields: Set[str],
        validation_results: Optional[List[ValidationIssue]] = None,
        applied_rules: Optional[List[str]] = None
    ) -> QualityScoreResult:
        """
        Calculate comprehensive quality score for a data row.
        
        Args:
            row: Data row as dictionary
            required_fields: Set of field names that are required (non-nullable)
            validation_results: Optional list of validation issues
            applied_rules: Optional list of rule IDs that were applied
        
        Returns:
            QualityScoreResult with all quality metrics
        """
        # Calculate completeness score
        completeness_score = self._calculate_completeness_score(
            row, required_fields
        )
        
        # Calculate validity score
        validity_score, issues = self._calculate_validity_score(
            row, validation_results or []
        )
        
        # Calculate overall score
        overall_score = (
            self.completeness_weight * completeness_score +
            self.validity_weight * validity_score
        )
        
        # Extract warnings
        warnings = [
            issue.message
            for issue in issues
            if issue.severity == ValidationSeverity.WARNING
        ]
        
        return QualityScoreResult(
            completeness_score=completeness_score,
            validity_score=validity_score,
            overall_score=overall_score,
            issues=issues,
            applied_rules=applied_rules or [],
            warnings=warnings
        )
    
    def _calculate_completeness_score(
        self,
        row: Dict[str, Any],
        required_fields: Set[str]
    ) -> float:
        """
        Calculate completeness score based on non-null required fields.
        
        Completeness = (number of non-null required fields) / (total required fields)
        
        Args:
            row: Data row as dictionary
            required_fields: Set of field names that are required
        
        Returns:
            Completeness score between 0.0 and 1.0
        """
        if not required_fields:
            # If no required fields, completeness is perfect
            return 1.0
        
        non_null_count = 0
        for field in required_fields:
            value = row.get(field)
            
            # Check if value is non-null and non-empty
            if value is not None:
                # For strings, also check if not empty after stripping
                if isinstance(value, str):
                    if value.strip():
                        non_null_count += 1
                else:
                    non_null_count += 1
        
        return non_null_count / len(required_fields)
    
    def _calculate_validity_score(
        self,
        row: Dict[str, Any],
        validation_results: List[ValidationIssue]
    ) -> tuple[float, List[ValidationIssue]]:
        """
        Calculate validity score based on validation results.
        
        Validity is calculated as:
        - Start with 1.0 (perfect score)
        - Deduct points for each ERROR-level issue
        - WARNING and INFO issues don't affect the score
        
        Args:
            row: Data row as dictionary
            validation_results: List of validation issues
        
        Returns:
            Tuple of (validity_score, all_issues)
        """
        # Count error-level issues
        error_count = sum(
            1 for issue in validation_results
            if issue.severity == ValidationSeverity.ERROR
        )
        
        # Calculate score
        # Each error reduces score by a fraction
        # Use logarithmic decay to avoid score going to 0 too quickly
        if error_count == 0:
            validity_score = 1.0
        else:
            # Deduct 0.1 per error, with minimum score of 0.0
            validity_score = max(0.0, 1.0 - (error_count * 0.1))
        
        return validity_score, validation_results
    
    def calculate_batch_quality_summary(
        self,
        quality_results: List[QualityScoreResult]
    ) -> Dict[str, Any]:
        """
        Calculate quality summary statistics for a batch of rows.
        
        Args:
            quality_results: List of QualityScoreResult for each row
        
        Returns:
            Dictionary with summary statistics
        """
        if not quality_results:
            return {
                "total_rows": 0,
                "avg_completeness_score": 0.0,
                "avg_validity_score": 0.0,
                "avg_overall_score": 0.0,
                "min_overall_score": 0.0,
                "max_overall_score": 0.0,
                "rows_with_warnings": 0,
                "rows_with_errors": 0,
                "total_errors": 0,
                "total_warnings": 0
            }
        
        total_completeness = sum(r.completeness_score for r in quality_results)
        total_validity = sum(r.validity_score for r in quality_results)
        total_overall = sum(r.overall_score for r in quality_results)
        
        rows_with_warnings = sum(
            1 for r in quality_results if r.warnings
        )
        
        rows_with_errors = sum(
            1 for r in quality_results
            if any(i.severity == ValidationSeverity.ERROR for i in r.issues)
        )
        
        total_errors = sum(
            sum(1 for i in r.issues if i.severity == ValidationSeverity.ERROR)
            for r in quality_results
        )
        
        total_warnings = sum(len(r.warnings) for r in quality_results)
        
        overall_scores = [r.overall_score for r in quality_results]
        
        return {
            "total_rows": len(quality_results),
            "avg_completeness_score": total_completeness / len(quality_results),
            "avg_validity_score": total_validity / len(quality_results),
            "avg_overall_score": total_overall / len(quality_results),
            "min_overall_score": min(overall_scores),
            "max_overall_score": max(overall_scores),
            "rows_with_warnings": rows_with_warnings,
            "rows_with_errors": rows_with_errors,
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "warning_rate": rows_with_warnings / len(quality_results),
            "error_rate": rows_with_errors / len(quality_results)
        }


def create_validation_issue(
    field_name: str,
    severity: ValidationSeverity,
    message: str,
    rule_id: Optional[str] = None
) -> ValidationIssue:
    """
    Helper function to create a ValidationIssue.
    
    Args:
        field_name: Name of the field with the issue
        severity: Severity level
        message: Description of the issue
        rule_id: Optional rule ID that detected the issue
    
    Returns:
        ValidationIssue instance
    """
    return ValidationIssue(
        field_name=field_name,
        severity=severity,
        message=message,
        rule_id=rule_id
    )
