"""
Unit tests for ExtractionStrategy interface

Tests cover:
1. Data model validation (Batch, ExtractionConfig)
2. Abstract interface contract
3. Base class helper methods (validate_config, generate_batch_id)
4. Idempotency of batch_id generation
5. Configuration validation
"""

import pytest
from extraction_strategy import (
    ExtractionStrategy,
    Batch,
    ExtractionConfig,
    ExtractionError,
    ValidationError
)


class TestBatchDataModel:
    """Tests for the Batch data model."""
    
    def test_batch_creation_with_required_fields(self):
        """Test creating a Batch with all required fields."""
        batch = Batch(
            rows=[{"id": 1, "name": "test"}],
            batch_id="batch_123",
            source_id="source_1",
            offset=0,
            total_rows=1,
            has_more=False
        )
        
        assert batch.rows == [{"id": 1, "name": "test"}]
        assert batch.batch_id == "batch_123"
        assert batch.source_id == "source_1"
        assert batch.offset == 0
        assert batch.total_rows == 1
        assert batch.has_more is False
        assert batch.metadata is None
    
    def test_batch_creation_with_metadata(self):
        """Test creating a Batch with optional metadata."""
        metadata = {"extraction_time": "2024-01-01T00:00:00", "file_size": 1024}
        batch = Batch(
            rows=[],
            batch_id="batch_456",
            source_id="source_2",
            offset=100,
            total_rows=0,
            has_more=True,
            metadata=metadata
        )
        
        assert batch.metadata == metadata
        assert batch.has_more is True
    
    def test_batch_empty_rows(self):
        """Test Batch can have empty rows list."""
        batch = Batch(
            rows=[],
            batch_id="batch_empty",
            source_id="source_3",
            offset=0,
            total_rows=0,
            has_more=False
        )
        
        assert batch.rows == []
        assert batch.total_rows == 0


class TestExtractionConfigDataModel:
    """Tests for the ExtractionConfig data model."""
    
    def test_config_creation_with_required_fields(self):
        """Test creating ExtractionConfig with required fields."""
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": "/data/test.csv"}
        )
        
        assert config.source_id == "test_source"
        assert config.source_type == "csv"
        assert config.connection_params == {"file_path": "/data/test.csv"}
        assert config.batch_size == 1000  # Default value
        assert config.schema_contract is None
        assert config.extraction_metadata is None
    
    def test_config_creation_with_custom_batch_size(self):
        """Test creating ExtractionConfig with custom batch size."""
        config = ExtractionConfig(
            source_id="test_source",
            source_type="database",
            connection_params={"host": "localhost"},
            batch_size=500
        )
        
        assert config.batch_size == 500
    
    def test_config_creation_with_schema_contract(self):
        """Test creating ExtractionConfig with schema contract."""
        schema = {
            "fields": [
                {"name": "id", "type": "integer"},
                {"name": "name", "type": "string"}
            ]
        }
        config = ExtractionConfig(
            source_id="test_source",
            source_type="database",
            connection_params={"host": "localhost"},
            schema_contract=schema
        )
        
        assert config.schema_contract == schema
    
    def test_config_creation_with_all_fields(self):
        """Test creating ExtractionConfig with all optional fields."""
        config = ExtractionConfig(
            source_id="test_source",
            source_type="api",
            connection_params={"url": "https://api.example.com"},
            batch_size=2000,
            schema_contract={"fields": []},
            extraction_metadata={"created_by": "admin"}
        )
        
        assert config.batch_size == 2000
        assert config.schema_contract == {"fields": []}
        assert config.extraction_metadata == {"created_by": "admin"}


class ConcreteExtractionStrategy(ExtractionStrategy):
    """Concrete implementation for testing the abstract base class."""
    
    def extract_batch(self, config, offset, limit):
        """Simple implementation that returns a test batch."""
        return Batch(
            rows=[{"id": i} for i in range(offset, offset + limit)],
            batch_id=self.generate_batch_id(config.source_id, offset),
            source_id=config.source_id,
            offset=offset,
            total_rows=limit,
            has_more=False
        )


class TestExtractionStrategyInterface:
    """Tests for the ExtractionStrategy abstract base class."""
    
    def test_cannot_instantiate_abstract_class(self):
        """Test that ExtractionStrategy cannot be instantiated directly."""
        with pytest.raises(TypeError):
            ExtractionStrategy()
    
    def test_concrete_implementation_can_be_instantiated(self):
        """Test that concrete implementations can be instantiated."""
        strategy = ConcreteExtractionStrategy()
        assert isinstance(strategy, ExtractionStrategy)
    
    def test_concrete_implementation_must_implement_extract_batch(self):
        """Test that concrete implementations must implement extract_batch."""
        
        class IncompleteStrategy(ExtractionStrategy):
            pass
        
        with pytest.raises(TypeError):
            IncompleteStrategy()


class TestValidateConfig:
    """Tests for the validate_config method."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.strategy = ConcreteExtractionStrategy()
    
    def test_validate_config_with_valid_config(self):
        """Test validation passes with valid config."""
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": "/data/test.csv"}
        )
        
        # Should not raise any exception
        self.strategy.validate_config(config)
    
    def test_validate_config_missing_source_id(self):
        """Test validation fails when source_id is empty."""
        config = ExtractionConfig(
            source_id="",
            source_type="csv",
            connection_params={"file_path": "/data/test.csv"}
        )
        
        with pytest.raises(ValueError, match="source_id is required"):
            self.strategy.validate_config(config)
    
    def test_validate_config_missing_source_type(self):
        """Test validation fails when source_type is empty."""
        config = ExtractionConfig(
            source_id="test_source",
            source_type="",
            connection_params={"file_path": "/data/test.csv"}
        )
        
        with pytest.raises(ValueError, match="source_type is required"):
            self.strategy.validate_config(config)
    
    def test_validate_config_invalid_batch_size_zero(self):
        """Test validation fails when batch_size is zero."""
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": "/data/test.csv"},
            batch_size=0
        )
        
        with pytest.raises(ValueError, match="batch_size must be positive"):
            self.strategy.validate_config(config)
    
    def test_validate_config_invalid_batch_size_negative(self):
        """Test validation fails when batch_size is negative."""
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={"file_path": "/data/test.csv"},
            batch_size=-100
        )
        
        with pytest.raises(ValueError, match="batch_size must be positive"):
            self.strategy.validate_config(config)
    
    def test_validate_config_missing_connection_params(self):
        """Test validation fails when connection_params is empty."""
        config = ExtractionConfig(
            source_id="test_source",
            source_type="csv",
            connection_params={}
        )
        
        with pytest.raises(ValueError, match="connection_params is required"):
            self.strategy.validate_config(config)


class TestGenerateBatchId:
    """Tests for the generate_batch_id method."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.strategy = ConcreteExtractionStrategy()
    
    def test_generate_batch_id_deterministic(self):
        """Test that batch_id generation is deterministic."""
        batch_id_1 = self.strategy.generate_batch_id("source_1", 0)
        batch_id_2 = self.strategy.generate_batch_id("source_1", 0)
        
        assert batch_id_1 == batch_id_2
    
    def test_generate_batch_id_different_sources(self):
        """Test that different sources produce different batch_ids."""
        batch_id_1 = self.strategy.generate_batch_id("source_1", 0)
        batch_id_2 = self.strategy.generate_batch_id("source_2", 0)
        
        assert batch_id_1 != batch_id_2
    
    def test_generate_batch_id_different_offsets(self):
        """Test that different offsets produce different batch_ids."""
        batch_id_1 = self.strategy.generate_batch_id("source_1", 0)
        batch_id_2 = self.strategy.generate_batch_id("source_1", 1000)
        
        assert batch_id_1 != batch_id_2
    
    def test_generate_batch_id_format(self):
        """Test that batch_id has expected format."""
        batch_id = self.strategy.generate_batch_id("testsource", 100)
        
        # Should start with "batch_"
        assert batch_id.startswith("batch_")
        
        # Should contain source_id
        assert "testsource" in batch_id
        
        # Should contain offset
        assert "100" in batch_id
        
        # Should contain hash (8 characters)
        parts = batch_id.split("_")
        assert len(parts) == 4  # batch, source_id, offset, hash
        assert len(parts[3]) == 8  # hash is 8 characters
    
    def test_generate_batch_id_idempotency_property(self):
        """Test idempotency property: same input always produces same output."""
        source_id = "customers_db"
        offset = 5000
        
        # Generate batch_id multiple times
        batch_ids = [
            self.strategy.generate_batch_id(source_id, offset)
            for _ in range(10)
        ]
        
        # All should be identical
        assert len(set(batch_ids)) == 1
    
    def test_generate_batch_id_with_special_characters(self):
        """Test batch_id generation with special characters in source_id."""
        batch_id = self.strategy.generate_batch_id("source-with-dashes", 0)
        
        assert "source-with-dashes" in batch_id
        assert batch_id.startswith("batch_")


class TestExtractionStrategyIntegration:
    """Integration tests for ExtractionStrategy usage."""
    
    def test_extract_batch_returns_correct_structure(self):
        """Test that extract_batch returns a properly structured Batch."""
        strategy = ConcreteExtractionStrategy()
        config = ExtractionConfig(
            source_id="test_source",
            source_type="test",
            connection_params={"test": "param"}
        )
        
        batch = strategy.extract_batch(config, offset=0, limit=10)
        
        assert isinstance(batch, Batch)
        assert batch.source_id == "test_source"
        assert batch.offset == 0
        assert batch.total_rows == 10
        assert len(batch.rows) == 10
    
    def test_extract_batch_with_different_offsets(self):
        """Test extracting batches with different offsets."""
        strategy = ConcreteExtractionStrategy()
        config = ExtractionConfig(
            source_id="test_source",
            source_type="test",
            connection_params={"test": "param"}
        )
        
        batch_1 = strategy.extract_batch(config, offset=0, limit=5)
        batch_2 = strategy.extract_batch(config, offset=5, limit=5)
        
        # Batches should have different offsets
        assert batch_1.offset == 0
        assert batch_2.offset == 5
        
        # Batches should have different batch_ids
        assert batch_1.batch_id != batch_2.batch_id
        
        # Batches should have different data
        assert batch_1.rows != batch_2.rows
    
    def test_batch_id_consistency_across_calls(self):
        """Test that batch_id is consistent for same offset."""
        strategy = ConcreteExtractionStrategy()
        config = ExtractionConfig(
            source_id="test_source",
            source_type="test",
            connection_params={"test": "param"}
        )
        
        batch_1 = strategy.extract_batch(config, offset=0, limit=10)
        batch_2 = strategy.extract_batch(config, offset=0, limit=10)
        
        # Same offset should produce same batch_id (idempotency)
        assert batch_1.batch_id == batch_2.batch_id


class TestExceptionClasses:
    """Tests for custom exception classes."""
    
    def test_extraction_error_can_be_raised(self):
        """Test that ExtractionError can be raised and caught."""
        with pytest.raises(ExtractionError):
            raise ExtractionError("Test extraction error")
    
    def test_extraction_error_with_message(self):
        """Test ExtractionError with custom message."""
        try:
            raise ExtractionError("Connection failed")
        except ExtractionError as e:
            assert str(e) == "Connection failed"
    
    def test_validation_error_can_be_raised(self):
        """Test that ValidationError can be raised and caught."""
        with pytest.raises(ValidationError):
            raise ValidationError("Test validation error")
    
    def test_validation_error_with_message(self):
        """Test ValidationError with custom message."""
        try:
            raise ValidationError("Schema mismatch")
        except ValidationError as e:
            assert str(e) == "Schema mismatch"
    
    def test_exceptions_are_distinct(self):
        """Test that ExtractionError and ValidationError are distinct."""
        assert ExtractionError != ValidationError
        
        # ExtractionError should not catch ValidationError
        with pytest.raises(ValidationError):
            try:
                raise ValidationError("test")
            except ExtractionError:
                pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
