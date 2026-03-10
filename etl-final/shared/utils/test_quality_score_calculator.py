"""
Unit tests for Quality Score Calculator
Tests completeness, validity, and overall quality score calculation.
"""
import pytest
from .quality_score_calculator import (
    QualityScoreCalculator,
    ValidationIssue,
    ValidationSeverity,
    QualityScoreResult,
    create_validation_issue
)


class TestQualityScoreCalculator:
    """Test QualityScoreCalculator class."""
    
    def test_initialization_default_weights(self):
        """Test calculator initialization with default weights."""
        calc = QualityScoreCalculator()
        
        assert calc.completeness_weight == 0.4
        assert calc.validity_weight == 0.6
    
    def test_initialization_custom_weights(self):
        """Test calculator initialization with custom weights."""
        calc = QualityScoreCalculator(
            completeness_weight=0.5,
            validity_weight=0.5
        )
        
        assert calc.completeness_weight == 0.5
        assert calc.validity_weight == 0.5
    
    def test_initialization_invalid_weights(self):
        """Test that invalid weights raise error."""
        with pytest.raises(ValueError, match="Weights must sum to 1.0"):
            QualityScoreCalculator(
                completeness_weight=0.5,
                validity_weight=0.6
            )
    
    def test_perfect_quality_score(self):
        """Test quality score for perfect data."""
        calc = QualityScoreCalculator()
        
        row = {
            "customer_id": 123,
            "name": "John Doe",
            "email": "john@example.com"
        }
        required_fields = {"customer_id", "name", "email"}
        
        result = calc.calculate_quality_score(row, required_fields)
        
        assert result.completeness_score == 1.0
        assert result.validity_score == 1.0
        assert result.overall_score == 1.0
        assert result.issues == []
        assert result.warnings == []
    
    def test_completeness_score_with_nulls(self):
        """Test completeness score when some required fields are null."""
        calc = QualityScoreCalculator()
        
        row = {
            "customer_id": 123,
            "name": None,  # Missing
            "email": "john@example.com"
        }
        required_fields = {"customer_id", "name", "email"}
        
        result = calc.calculate_quality_score(row, required_fields)
        
        # 2 out of 3 required fields are non-null
        assert result.completeness_score == pytest.approx(2/3, abs=0.01)
    
    def test_completeness_score_with_empty_strings(self):
        """Test that empty strings are treated as missing."""
        calc = QualityScoreCalculator()
        
        row = {
            "customer_id": 123,
            "name": "   ",  # Empty after stripping
            "email": "john@example.com"
        }
        required_fields = {"customer_id", "name", "email"}
        
        result = calc.calculate_quality_score(row, required_fields)
        
        # 2 out of 3 required fields are non-null and non-empty
        assert result.completeness_score == pytest.approx(2/3, abs=0.01)
    
    def test_completeness_score_no_required_fields(self):
        """Test completeness score when no fields are required."""
        calc = QualityScoreCalculator()
        
        row = {"optional_field": None}
        required_fields = set()
        
        result = calc.calculate_quality_score(row, required_fields)
        
        # No required fields means perfect completeness
        assert result.completeness_score == 1.0
    
    def test_validity_score_with_errors(self):
        """Test validity score with validation errors."""
        calc = QualityScoreCalculator()
        
        row = {"email": "invalid-email"}
        required_fields = {"email"}
        
        validation_results = [
            create_validation_issue(
                "email",
                ValidationSeverity.ERROR,
                "Invalid email format"
            )
        ]
        
        result = calc.calculate_quality_score(
            row,
            required_fields,
            validation_results
        )
        
        # 1 error reduces score by 0.1
        assert result.validity_score == pytest.approx(0.9, abs=0.01)
    
    def test_validity_score_with_multiple_errors(self):
        """Test validity score with multiple validation errors."""
        calc = QualityScoreCalculator()
        
        row = {
            "email": "invalid",
            "age": -5
        }
        required_fields = {"email", "age"}
        
        validation_results = [
            create_validation_issue(
                "email",
                ValidationSeverity.ERROR,
                "Invalid email format"
            ),
            create_validation_issue(
                "age",
                ValidationSeverity.ERROR,
                "Age cannot be negative"
            )
        ]
        
        result = calc.calculate_quality_score(
            row,
            required_fields,
            validation_results
        )
        
        # 2 errors reduce score by 0.2
        assert result.validity_score == pytest.approx(0.8, abs=0.01)
    
    def test_validity_score_with_warnings(self):
        """Test that warnings don't affect validity score."""
        calc = QualityScoreCalculator()
        
        row = {"name": "John"}
        required_fields = {"name"}
        
        validation_results = [
            create_validation_issue(
                "name",
                ValidationSeverity.WARNING,
                "Name is very short"
            )
        ]
        
        result = calc.calculate_quality_score(
            row,
            required_fields,
            validation_results
        )
        
        # Warnings don't affect validity score
        assert result.validity_score == 1.0
        assert len(result.warnings) == 1
        assert "Name is very short" in result.warnings
    
    def test_validity_score_minimum_zero(self):
        """Test that validity score doesn't go below 0."""
        calc = QualityScoreCalculator()
        
        row = {"field": "value"}
        required_fields = {"field"}
        
        # Create 20 errors (would be -1.0 without minimum)
        validation_results = [
            create_validation_issue(
                f"field{i}",
                ValidationSeverity.ERROR,
                f"Error {i}"
            )
            for i in range(20)
        ]
        
        result = calc.calculate_quality_score(
            row,
            required_fields,
            validation_results
        )
        
        # Score should be 0.0, not negative
        assert result.validity_score == 0.0
    
    def test_overall_score_calculation(self):
        """Test overall score as weighted average."""
        calc = QualityScoreCalculator(
            completeness_weight=0.4,
            validity_weight=0.6
        )
        
        row = {
            "field1": "value1",
            "field2": None  # Missing
        }
        required_fields = {"field1", "field2"}
        
        validation_results = [
            create_validation_issue(
                "field1",
                ValidationSeverity.ERROR,
                "Validation error"
            )
        ]
        
        result = calc.calculate_quality_score(
            row,
            required_fields,
            validation_results
        )
        
        # Completeness: 1/2 = 0.5
        # Validity: 1 error = 0.9
        # Overall: 0.4 * 0.5 + 0.6 * 0.9 = 0.2 + 0.54 = 0.74
        assert result.completeness_score == pytest.approx(0.5, abs=0.01)
        assert result.validity_score == pytest.approx(0.9, abs=0.01)
        assert result.overall_score == pytest.approx(0.74, abs=0.01)
    
    def test_applied_rules_tracking(self):
        """Test that applied rules are tracked."""
        calc = QualityScoreCalculator()
        
        row = {"field": "value"}
        required_fields = {"field"}
        applied_rules = ["trim_strings", "validate_email", "normalize_case"]
        
        result = calc.calculate_quality_score(
            row,
            required_fields,
            applied_rules=applied_rules
        )
        
        assert result.applied_rules == applied_rules
    
    def test_issues_tracking(self):
        """Test that all issues are tracked in result."""
        calc = QualityScoreCalculator()
        
        row = {"field": "value"}
        required_fields = {"field"}
        
        validation_results = [
            create_validation_issue(
                "field1",
                ValidationSeverity.ERROR,
                "Error message"
            ),
            create_validation_issue(
                "field2",
                ValidationSeverity.WARNING,
                "Warning message"
            ),
            create_validation_issue(
                "field3",
                ValidationSeverity.INFO,
                "Info message"
            )
        ]
        
        result = calc.calculate_quality_score(
            row,
            required_fields,
            validation_results
        )
        
        assert len(result.issues) == 3
        assert result.issues[0].severity == ValidationSeverity.ERROR
        assert result.issues[1].severity == ValidationSeverity.WARNING
        assert result.issues[2].severity == ValidationSeverity.INFO


class TestBatchQualitySummary:
    """Test batch quality summary calculation."""
    
    def test_empty_batch_summary(self):
        """Test summary for empty batch."""
        calc = QualityScoreCalculator()
        
        summary = calc.calculate_batch_quality_summary([])
        
        assert summary["total_rows"] == 0
        assert summary["avg_completeness_score"] == 0.0
        assert summary["avg_validity_score"] == 0.0
        assert summary["avg_overall_score"] == 0.0
    
    def test_batch_summary_averages(self):
        """Test that batch summary calculates correct averages."""
        calc = QualityScoreCalculator()
        
        results = [
            QualityScoreResult(
                completeness_score=1.0,
                validity_score=1.0,
                overall_score=1.0,
                issues=[],
                applied_rules=[],
                warnings=[]
            ),
            QualityScoreResult(
                completeness_score=0.8,
                validity_score=0.9,
                overall_score=0.86,
                issues=[],
                applied_rules=[],
                warnings=[]
            ),
            QualityScoreResult(
                completeness_score=0.6,
                validity_score=0.7,
                overall_score=0.66,
                issues=[],
                applied_rules=[],
                warnings=[]
            )
        ]
        
        summary = calc.calculate_batch_quality_summary(results)
        
        assert summary["total_rows"] == 3
        assert summary["avg_completeness_score"] == pytest.approx(0.8, abs=0.01)
        assert summary["avg_validity_score"] == pytest.approx(0.867, abs=0.01)
        assert summary["avg_overall_score"] == pytest.approx(0.84, abs=0.01)
    
    def test_batch_summary_min_max(self):
        """Test that batch summary includes min/max scores."""
        calc = QualityScoreCalculator()
        
        results = [
            QualityScoreResult(
                completeness_score=1.0,
                validity_score=1.0,
                overall_score=0.95,
                issues=[],
                applied_rules=[],
                warnings=[]
            ),
            QualityScoreResult(
                completeness_score=0.5,
                validity_score=0.6,
                overall_score=0.56,
                issues=[],
                applied_rules=[],
                warnings=[]
            ),
            QualityScoreResult(
                completeness_score=0.8,
                validity_score=0.9,
                overall_score=0.86,
                issues=[],
                applied_rules=[],
                warnings=[]
            )
        ]
        
        summary = calc.calculate_batch_quality_summary(results)
        
        assert summary["min_overall_score"] == pytest.approx(0.56, abs=0.01)
        assert summary["max_overall_score"] == pytest.approx(0.95, abs=0.01)
    
    def test_batch_summary_warning_counts(self):
        """Test that batch summary counts warnings correctly."""
        calc = QualityScoreCalculator()
        
        results = [
            QualityScoreResult(
                completeness_score=1.0,
                validity_score=1.0,
                overall_score=1.0,
                issues=[],
                applied_rules=[],
                warnings=["Warning 1", "Warning 2"]
            ),
            QualityScoreResult(
                completeness_score=1.0,
                validity_score=1.0,
                overall_score=1.0,
                issues=[],
                applied_rules=[],
                warnings=[]
            ),
            QualityScoreResult(
                completeness_score=1.0,
                validity_score=1.0,
                overall_score=1.0,
                issues=[],
                applied_rules=[],
                warnings=["Warning 3"]
            )
        ]
        
        summary = calc.calculate_batch_quality_summary(results)
        
        assert summary["rows_with_warnings"] == 2
        assert summary["total_warnings"] == 3
        assert summary["warning_rate"] == pytest.approx(2/3, abs=0.01)
    
    def test_batch_summary_error_counts(self):
        """Test that batch summary counts errors correctly."""
        calc = QualityScoreCalculator()
        
        results = [
            QualityScoreResult(
                completeness_score=1.0,
                validity_score=0.9,
                overall_score=0.96,
                issues=[
                    create_validation_issue("f1", ValidationSeverity.ERROR, "E1"),
                    create_validation_issue("f2", ValidationSeverity.ERROR, "E2")
                ],
                applied_rules=[],
                warnings=[]
            ),
            QualityScoreResult(
                completeness_score=1.0,
                validity_score=1.0,
                overall_score=1.0,
                issues=[],
                applied_rules=[],
                warnings=[]
            ),
            QualityScoreResult(
                completeness_score=1.0,
                validity_score=0.9,
                overall_score=0.96,
                issues=[
                    create_validation_issue("f3", ValidationSeverity.ERROR, "E3")
                ],
                applied_rules=[],
                warnings=[]
            )
        ]
        
        summary = calc.calculate_batch_quality_summary(results)
        
        assert summary["rows_with_errors"] == 2
        assert summary["total_errors"] == 3
        assert summary["error_rate"] == pytest.approx(2/3, abs=0.01)


class TestValidationIssueCreation:
    """Test ValidationIssue creation helper."""
    
    def test_create_validation_issue_basic(self):
        """Test creating a basic validation issue."""
        issue = create_validation_issue(
            "email",
            ValidationSeverity.ERROR,
            "Invalid email format"
        )
        
        assert issue.field_name == "email"
        assert issue.severity == ValidationSeverity.ERROR
        assert issue.message == "Invalid email format"
        assert issue.rule_id is None
    
    def test_create_validation_issue_with_rule_id(self):
        """Test creating a validation issue with rule ID."""
        issue = create_validation_issue(
            "age",
            ValidationSeverity.WARNING,
            "Age seems unusual",
            rule_id="validate_age_range"
        )
        
        assert issue.field_name == "age"
        assert issue.severity == ValidationSeverity.WARNING
        assert issue.message == "Age seems unusual"
        assert issue.rule_id == "validate_age_range"
