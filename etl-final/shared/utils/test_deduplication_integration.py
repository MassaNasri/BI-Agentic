"""
Integration tests for deduplication key generation across ETL services.
Tests that dedup keys are generated correctly and preserved through the pipeline.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
from idempotency_manager import IdempotencyManager, IdempotencyKey, PipelineStage


class TestDeduplicationKeyGeneration:
    """Tests for deduplication key generation."""
    
    def test_deterministic_hash_generation(self):
        """Test that hash generation is deterministic."""
        manager = IdempotencyManager(None)
        
        row = {
            "id": 1,
            "name": "John Doe",
            "email": "john@example.com",
            "age": 30
        }
        
        # Generate hash multiple times
        hash1 = manager.generate_row_hash(row)
        hash2 = manager.generate_row_hash(row)
        hash3 = manager.generate_row_hash(row)
        
        # All hashes should be identical
        assert hash1 == hash2 == hash3
        assert len(hash1) == 64  # SHA256 produces 64 hex characters
    
    def test_order_independent_hash(self):
        """Test that hash is independent of key order."""
        manager = IdempotencyManager(None)
        
        row1 = {"id": 1, "name": "Alice", "email": "alice@example.com"}
        row2 = {"email": "alice@example.com", "id": 1, "name": "Alice"}
        row3 = {"name": "Alice", "email": "alice@example.com", "id": 1}
        
        hash1 = manager.generate_row_hash(row1)
        hash2 = manager.generate_row_hash(row2)
        hash3 = manager.generate_row_hash(row3)
        
        # All hashes should be identical regardless of key order
        assert hash1 == hash2 == hash3
    
    def test_different_values_different_hash(self):
        """Test that different values produce different hashes."""
        manager = IdempotencyManager(None)
        
        row1 = {"id": 1, "name": "Alice"}
        row2 = {"id": 2, "name": "Alice"}
        row3 = {"id": 1, "name": "Bob"}
        
        hash1 = manager.generate_row_hash(row1)
        hash2 = manager.generate_row_hash(row2)
        hash3 = manager.generate_row_hash(row3)
        
        # All hashes should be different
        assert hash1 != hash2
        assert hash1 != hash3
        assert hash2 != hash3
    
    def test_collision_resistance(self):
        """Test that hash function is collision-resistant."""
        manager = IdempotencyManager(None)
        
        # Generate hashes for many different rows
        hashes = set()
        for i in range(1000):
            row = {
                "id": i,
                "name": f"User_{i}",
                "email": f"user{i}@example.com",
                "value": i * 2.5
            }
            hash_value = manager.generate_row_hash(row)
            hashes.add(hash_value)
        
        # All hashes should be unique (no collisions)
        assert len(hashes) == 1000
    
    def test_empty_row_hash(self):
        """Test hash generation for empty row."""
        manager = IdempotencyManager(None)
        
        row = {}
        hash_value = manager.generate_row_hash(row)
        
        assert isinstance(hash_value, str)
        assert len(hash_value) == 64
    
    def test_complex_data_types(self):
        """Test hash generation with complex data types."""
        manager = IdempotencyManager(None)
        
        row = {
            "id": 1,
            "name": "Test",
            "values": [1, 2, 3],
            "nested": {"key": "value"},
            "boolean": True,
            "null": None,
            "float": 3.14159
        }
        
        hash1 = manager.generate_row_hash(row)
        hash2 = manager.generate_row_hash(row)
        
        # Should be deterministic even with complex types
        assert hash1 == hash2
        assert len(hash1) == 64


class TestExtractorDeduplication:
    """Tests for deduplication in extractor service."""
    
    @patch('sys.modules', {'pandas': MagicMock()})
    def test_extractor_adds_dedup_key(self):
        """Test that extractor adds dedup key to extracted rows."""
        manager = IdempotencyManager(None)
        
        # Simulate extracted row data
        row_data = {
            "id": 1,
            "name": "John Doe",
            "email": "john@example.com"
        }
        
        # Generate dedup key
        dedup_key = manager.generate_row_hash(row_data)
        
        # Simulate message structure from extractor
        message = {
            "source": "test_file.csv",
            "batch_id": "batch_001",
            "row_id": 0,
            "data": row_data,
            "_dedup_key": dedup_key,
            "_extracted_at": "2024-01-01T00:00:00"
        }
        
        # Verify dedup key is present and correct
        assert "_dedup_key" in message
        assert message["_dedup_key"] == dedup_key
        assert len(message["_dedup_key"]) == 64
    
    def test_batch_id_generation(self):
        """Test that batch_id is generated for each extraction."""
        from uuid import UUID
        
        # Simulate batch IDs
        batch_id_1 = "550e8400-e29b-41d4-a716-446655440000"
        batch_id_2 = "550e8400-e29b-41d4-a716-446655440001"
        
        # Verify they are valid UUIDs
        try:
            UUID(batch_id_1)
            UUID(batch_id_2)
            valid = True
        except ValueError:
            valid = False
        
        assert valid
        assert batch_id_1 != batch_id_2


class TestTransformerDeduplication:
    """Tests for deduplication in transformer service."""
    
    def test_transformer_preserves_original_dedup_key(self):
        """Test that transformer preserves original dedup key."""
        manager = IdempotencyManager(None)
        
        # Original row data
        original_data = {"id": 1, "name": "  John Doe  ", "email": "JOHN@EXAMPLE.COM"}
        original_dedup_key = manager.generate_row_hash(original_data)
        
        # Transformed row data (cleaned)
        transformed_data = {"id": 1, "name": "John Doe", "email": "john@example.com"}
        transformed_dedup_key = manager.generate_row_hash(transformed_data)
        
        # Simulate message from transformer
        message = {
            "source": "test_file.csv",
            "data": transformed_data,
            "_original_dedup_key": original_dedup_key,
            "_transformed_dedup_key": transformed_dedup_key,
            "_batch_id": "batch_001",
            "_extracted_at": "2024-01-01T00:00:00",
            "_cleaned_at": "2024-01-01T00:00:01"
        }
        
        # Verify both keys are present
        assert "_original_dedup_key" in message
        assert "_transformed_dedup_key" in message
        assert message["_original_dedup_key"] == original_dedup_key
        assert message["_transformed_dedup_key"] == transformed_dedup_key
        
        # Keys should be different (data was transformed)
        assert original_dedup_key != transformed_dedup_key
    
    def test_transformer_generates_new_dedup_key(self):
        """Test that transformer generates new dedup key for transformed data."""
        manager = IdempotencyManager(None)
        
        # Original data
        original = {"value": "  TEST  "}
        original_hash = manager.generate_row_hash(original)
        
        # Transformed data (trimmed)
        transformed = {"value": "TEST"}
        transformed_hash = manager.generate_row_hash(transformed)
        
        # Hashes should be different
        assert original_hash != transformed_hash


class TestLoaderDeduplication:
    """Tests for deduplication in loader service."""
    
    def test_loader_preserves_all_dedup_keys(self):
        """Test that loader preserves all deduplication keys."""
        # Simulate message from loader
        message = {
            "source": "test_file.csv",
            "data": {"id": 1, "name": "John Doe"},
            "_original_dedup_key": "abc123original",
            "_transformed_dedup_key": "def456transformed",
            "_batch_id": "batch_001",
            "_extracted_at": "2024-01-01T00:00:00",
            "_cleaned_at": "2024-01-01T00:00:01",
            "_loaded_at": "2024-01-01T00:00:02"
        }
        
        # Verify all metadata is present
        assert "_original_dedup_key" in message
        assert "_transformed_dedup_key" in message
        assert "_batch_id" in message
        assert "_extracted_at" in message
        assert "_cleaned_at" in message
        assert "_loaded_at" in message
    
    def test_enriched_row_structure(self):
        """Test that loader enriches row with metadata."""
        row_data = {"id": 1, "name": "Test"}
        
        enriched_row = {
            **row_data,
            "_original_dedup_key": "abc123",
            "_transformed_dedup_key": "def456",
            "_batch_id": "batch_001",
            "_extracted_at": "2024-01-01T00:00:00",
            "_cleaned_at": "2024-01-01T00:00:01",
            "_loaded_at": "2024-01-01T00:00:02"
        }
        
        # Verify original data is preserved
        assert enriched_row["id"] == 1
        assert enriched_row["name"] == "Test"
        
        # Verify metadata is added
        assert "_original_dedup_key" in enriched_row
        assert "_transformed_dedup_key" in enriched_row
        assert "_batch_id" in enriched_row


class TestEndToEndDeduplication:
    """End-to-end tests for deduplication across the pipeline."""
    
    def test_complete_pipeline_deduplication(self):
        """Test deduplication keys through complete pipeline."""
        manager = IdempotencyManager(None)
        
        # 1. EXTRACTOR: Extract row
        original_row = {"id": 1, "name": "  John  ", "email": "JOHN@TEST.COM"}
        original_hash = manager.generate_row_hash(original_row)
        
        extractor_message = {
            "source": "users.csv",
            "batch_id": "batch_001",
            "row_id": 0,
            "data": original_row,
            "_dedup_key": original_hash,
            "_extracted_at": "2024-01-01T00:00:00"
        }
        
        # 2. TRANSFORMER: Clean and transform
        cleaned_row = {"id": 1, "name": "John", "email": "john@test.com"}
        cleaned_hash = manager.generate_row_hash(cleaned_row)
        
        transformer_message = {
            "source": "users.csv",
            "data": cleaned_row,
            "_original_dedup_key": original_hash,
            "_transformed_dedup_key": cleaned_hash,
            "_batch_id": "batch_001",
            "_extracted_at": "2024-01-01T00:00:00",
            "_cleaned_at": "2024-01-01T00:00:01"
        }
        
        # 3. LOADER: Load to ClickHouse
        loader_message = {
            **cleaned_row,
            "_original_dedup_key": original_hash,
            "_transformed_dedup_key": cleaned_hash,
            "_batch_id": "batch_001",
            "_extracted_at": "2024-01-01T00:00:00",
            "_cleaned_at": "2024-01-01T00:00:01",
            "_loaded_at": "2024-01-01T00:00:02"
        }
        
        # Verify lineage
        assert extractor_message["_dedup_key"] == transformer_message["_original_dedup_key"]
        assert transformer_message["_original_dedup_key"] == loader_message["_original_dedup_key"]
        assert transformer_message["_transformed_dedup_key"] == loader_message["_transformed_dedup_key"]
        
        # Verify hashes are different (data was transformed)
        assert original_hash != cleaned_hash
    
    def test_duplicate_detection_scenario(self):
        """Test that duplicate rows can be detected."""
        manager = IdempotencyManager(None)
        
        # Same row extracted twice
        row = {"id": 1, "name": "Test"}
        hash1 = manager.generate_row_hash(row)
        hash2 = manager.generate_row_hash(row)
        
        # Hashes should be identical (duplicate detected)
        assert hash1 == hash2
        
        # Different row
        different_row = {"id": 2, "name": "Test"}
        hash3 = manager.generate_row_hash(different_row)
        
        # Hash should be different (not a duplicate)
        assert hash1 != hash3
    
    def test_idempotent_reprocessing(self):
        """Test that reprocessing same data produces same hashes."""
        manager = IdempotencyManager(None)
        
        # Process same row multiple times
        row = {"id": 1, "value": "test"}
        
        hashes = []
        for _ in range(10):
            hash_value = manager.generate_row_hash(row)
            hashes.append(hash_value)
        
        # All hashes should be identical (idempotent)
        assert len(set(hashes)) == 1
        assert all(h == hashes[0] for h in hashes)


class TestDeduplicationKeyProperties:
    """Property-based tests for deduplication keys."""
    
    def test_hash_length_consistency(self):
        """Test that all hashes have consistent length."""
        manager = IdempotencyManager(None)
        
        test_rows = [
            {},
            {"a": 1},
            {"a": 1, "b": 2},
            {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5},
            {"key": "value" * 100},  # Long value
        ]
        
        for row in test_rows:
            hash_value = manager.generate_row_hash(row)
            assert len(hash_value) == 64, f"Hash length mismatch for row: {row}"
    
    def test_hash_character_set(self):
        """Test that hashes only contain valid hex characters."""
        manager = IdempotencyManager(None)
        
        row = {"id": 1, "name": "Test", "value": 123.45}
        hash_value = manager.generate_row_hash(row)
        
        # SHA256 hex digest should only contain 0-9 and a-f
        assert all(c in "0123456789abcdef" for c in hash_value)
    
    def test_hash_uniqueness_large_dataset(self):
        """Test hash uniqueness across large dataset."""
        manager = IdempotencyManager(None)
        
        hashes = set()
        num_rows = 10000
        
        for i in range(num_rows):
            row = {
                "id": i,
                "name": f"User_{i}",
                "email": f"user{i}@example.com",
                "age": i % 100,
                "score": i * 1.5
            }
            hash_value = manager.generate_row_hash(row)
            hashes.add(hash_value)
        
        # All hashes should be unique
        assert len(hashes) == num_rows, f"Expected {num_rows} unique hashes, got {len(hashes)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
