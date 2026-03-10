"""
Unit tests for Rule Versioning and Change Tracking.

Tests cover:
- ChangeType enum
- RuleVersion creation and validation
- RuleChange tracking
- RuleVersionHistory management
- RuleVersionManager operations
- Version comparison and integrity verification
"""
import pytest
import json
from datetime import datetime, timedelta
from uuid import UUID
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.models.rule_versioning import (
    ChangeType,
    RuleVersion,
    RuleChange,
    RuleVersionHistory,
    RuleVersionManager
)


class TestChangeType:
    """Tests for ChangeType enum."""
    
    def test_change_types_exist(self):
        """Test that all required change types are defined."""
        assert ChangeType.CREATED.value == "CREATED"
        assert ChangeType.MODIFIED.value == "MODIFIED"
        assert ChangeType.DEPRECATED.value == "DEPRECATED"
        assert ChangeType.DELETED.value == "DELETED"
        assert ChangeType.ACTIVATED.value == "ACTIVATED"
        assert ChangeType.DEACTIVATED.value == "DEACTIVATED"
    
    def test_change_type_count(self):
        """Test that exactly 6 change types are defined."""
        assert len(ChangeType) == 6


class TestRuleVersion:
    """Tests for RuleVersion data model."""
    
    def test_create_valid_version(self):
        """Test creating a valid rule version."""
        rule_content = json.dumps({"rule_id": "test", "priority": 1})
        version = RuleVersion(
            rule_id="test_rule_v1",
            version_number="1.0.0",
            created_by="admin",
            rule_hash=RuleVersion.compute_hash(rule_content),
            rule_content=rule_content,
            change_description="Initial version"
        )
        
        assert version.rule_id == "test_rule_v1"
        assert version.version_number == "1.0.0"
        assert version.created_by == "admin"
        assert isinstance(version.version_id, UUID)
        assert isinstance(version.created_at, datetime)
        assert version.is_active is True
        assert version.change_description == "Initial version"
    
    def test_version_id_auto_generated(self):
        """Test that version_id is automatically generated as UUID."""
        version1 = RuleVersion(rule_id="test", version_number="1.0.0")
        version2 = RuleVersion(rule_id="test", version_number="1.0.1")
        
        assert isinstance(version1.version_id, UUID)
        assert isinstance(version2.version_id, UUID)
        assert version1.version_id != version2.version_id
    
    def test_empty_rule_id_raises_error(self):
        """Test that empty rule_id raises ValueError."""
        with pytest.raises(ValueError, match="rule_id cannot be empty"):
            RuleVersion(rule_id="", version_number="1.0.0")
    
    def test_empty_version_number_raises_error(self):
        """Test that empty version_number raises ValueError."""
        with pytest.raises(ValueError, match="version_number cannot be empty"):
            RuleVersion(rule_id="test", version_number="")
    
    def test_invalid_semantic_version_raises_error(self):
        """Test that invalid semantic version raises ValueError."""
        invalid_versions = ["1.0", "1", "1.0.0.0", "v1.0.0", "1.0.x", "abc"]
        
        for invalid_version in invalid_versions:
            with pytest.raises(ValueError, match="Invalid semantic version"):
                RuleVersion(rule_id="test", version_number=invalid_version)
    
    def test_valid_semantic_versions(self):
        """Test that valid semantic versions are accepted."""
        valid_versions = ["1.0.0", "0.0.1", "10.20.30", "999.999.999"]
        
        for valid_version in valid_versions:
            version = RuleVersion(rule_id="test", version_number=valid_version)
            assert version.version_number == valid_version
    
    def test_compute_hash(self):
        """Test hash computation for rule content."""
        content1 = "test content"
        content2 = "test content"
        content3 = "different content"
        
        hash1 = RuleVersion.compute_hash(content1)
        hash2 = RuleVersion.compute_hash(content2)
        hash3 = RuleVersion.compute_hash(content3)
        
        # Same content produces same hash
        assert hash1 == hash2
        
        # Different content produces different hash
        assert hash1 != hash3
        
        # Hash is hexadecimal string
        assert len(hash1) == 64  # SHA256 produces 64 hex characters
        assert all(c in '0123456789abcdef' for c in hash1)
    
    def test_default_values(self):
        """Test that fields have correct default values."""
        version = RuleVersion(rule_id="test", version_number="1.0.0")
        
        assert isinstance(version.version_id, UUID)
        assert version.created_by == ""
        assert version.rule_hash == ""
        assert version.rule_content == ""
        assert version.is_active is True
        assert version.change_description == ""
        assert version.metadata == {}


class TestRuleChange:
    """Tests for RuleChange data model."""
    
    def test_create_valid_change(self):
        """Test creating a valid rule change."""
        change = RuleChange(
            rule_id="test_rule",
            from_version="1.0.0",
            to_version="1.1.0",
            change_type=ChangeType.MODIFIED,
            changed_by="admin",
            change_description="Updated priority",
            field_changes={"priority": (1, 2)}
        )
        
        assert isinstance(change.change_id, UUID)
        assert change.rule_id == "test_rule"
        assert change.from_version == "1.0.0"
        assert change.to_version == "1.1.0"
        assert change.change_type == ChangeType.MODIFIED
        assert change.changed_by == "admin"
        assert isinstance(change.changed_at, datetime)
        assert change.field_changes["priority"] == (1, 2)
    
    def test_change_id_auto_generated(self):
        """Test that change_id is automatically generated as UUID."""
        change1 = RuleChange()
        change2 = RuleChange()
        
        assert isinstance(change1.change_id, UUID)
        assert isinstance(change2.change_id, UUID)
        assert change1.change_id != change2.change_id
    
    def test_creation_change_has_no_from_version(self):
        """Test that creation changes have None as from_version."""
        change = RuleChange(
            rule_id="test_rule",
            from_version=None,
            to_version="1.0.0",
            change_type=ChangeType.CREATED
        )
        
        assert change.from_version is None
        assert change.to_version == "1.0.0"
        assert change.change_type == ChangeType.CREATED
    
    def test_default_values(self):
        """Test that fields have correct default values."""
        change = RuleChange()
        
        assert isinstance(change.change_id, UUID)
        assert change.rule_id == ""
        assert change.from_version is None
        assert change.to_version == ""
        assert change.change_type == ChangeType.MODIFIED
        assert isinstance(change.changed_at, datetime)
        assert change.changed_by == ""
        assert change.change_description == ""
        assert change.field_changes == {}
        assert change.metadata == {}


class TestRuleVersionHistory:
    """Tests for RuleVersionHistory data model."""
    
    def test_create_empty_history(self):
        """Test creating an empty version history."""
        history = RuleVersionHistory(rule_id="test_rule")
        
        assert history.rule_id == "test_rule"
        assert history.versions == []
        assert history.changes == []
        assert history.current_version is None
    
    def test_get_version(self):
        """Test retrieving a specific version."""
        history = RuleVersionHistory(rule_id="test_rule")
        
        version1 = RuleVersion(rule_id="test_rule", version_number="1.0.0")
        version2 = RuleVersion(rule_id="test_rule", version_number="1.1.0")
        
        history.versions = [version1, version2]
        
        retrieved = history.get_version("1.0.0")
        assert retrieved == version1
        
        retrieved = history.get_version("1.1.0")
        assert retrieved == version2
        
        retrieved = history.get_version("2.0.0")
        assert retrieved is None
    
    def test_get_active_version(self):
        """Test retrieving the active version."""
        history = RuleVersionHistory(rule_id="test_rule")
        
        version1 = RuleVersion(rule_id="test_rule", version_number="1.0.0", is_active=False)
        version2 = RuleVersion(rule_id="test_rule", version_number="1.1.0", is_active=True)
        version3 = RuleVersion(rule_id="test_rule", version_number="1.2.0", is_active=False)
        
        history.versions = [version1, version2, version3]
        
        active = history.get_active_version()
        assert active == version2
        assert active.version_number == "1.1.0"
    
    def test_get_active_version_when_none_active(self):
        """Test get_active_version returns None when no version is active."""
        history = RuleVersionHistory(rule_id="test_rule")
        
        version1 = RuleVersion(rule_id="test_rule", version_number="1.0.0", is_active=False)
        history.versions = [version1]
        
        active = history.get_active_version()
        assert active is None
    
    def test_get_changes_between(self):
        """Test retrieving changes between two versions."""
        history = RuleVersionHistory(rule_id="test_rule")
        
        # Create versions with different timestamps
        now = datetime.utcnow()
        version1 = RuleVersion(rule_id="test_rule", version_number="1.0.0")
        version1.created_at = now
        
        version2 = RuleVersion(rule_id="test_rule", version_number="1.1.0")
        version2.created_at = now + timedelta(hours=1)
        
        version3 = RuleVersion(rule_id="test_rule", version_number="1.2.0")
        version3.created_at = now + timedelta(hours=2)
        
        history.versions = [version1, version2, version3]
        
        # Create changes
        change1 = RuleChange(rule_id="test_rule", from_version="1.0.0", to_version="1.1.0")
        change1.changed_at = now + timedelta(minutes=30)
        
        change2 = RuleChange(rule_id="test_rule", from_version="1.1.0", to_version="1.2.0")
        change2.changed_at = now + timedelta(hours=1, minutes=30)
        
        history.changes = [change1, change2]
        
        # Get changes between 1.0.0 and 1.2.0
        changes = history.get_changes_between("1.0.0", "1.2.0")
        assert len(changes) == 2
        assert change1 in changes
        assert change2 in changes


class TestRuleVersionManager:
    """Tests for RuleVersionManager."""
    
    def test_create_first_version(self):
        """Test creating the first version of a rule."""
        manager = RuleVersionManager()
        
        rule_content = json.dumps({"rule_id": "test", "priority": 1})
        version = manager.create_rule_version(
            rule_id="test_rule",
            version_number="1.0.0",
            rule_content=rule_content,
            created_by="admin",
            change_description="Initial version"
        )
        
        assert version.rule_id == "test_rule"
        assert version.version_number == "1.0.0"
        assert version.created_by == "admin"
        assert version.rule_content == rule_content
        assert version.is_active is False  # Not active by default
        
        # Check history was created
        history = manager.get_version_history("test_rule")
        assert history is not None
        assert len(history.versions) == 1
        assert len(history.changes) == 1
        assert history.changes[0].change_type == ChangeType.CREATED
    
    def test_create_subsequent_version(self):
        """Test creating a subsequent version of a rule."""
        manager = RuleVersionManager()
        
        # Create first version
        content1 = json.dumps({"rule_id": "test", "priority": 1})
        manager.create_rule_version(
            rule_id="test_rule",
            version_number="1.0.0",
            rule_content=content1,
            created_by="admin"
        )
        
        # Activate first version
        manager.activate_version("test_rule", "1.0.0", "admin")
        
        # Create second version
        content2 = json.dumps({"rule_id": "test", "priority": 2})
        version2 = manager.create_rule_version(
            rule_id="test_rule",
            version_number="1.1.0",
            rule_content=content2,
            created_by="admin",
            change_description="Updated priority"
        )
        
        assert version2.version_number == "1.1.0"
        
        # Check history
        history = manager.get_version_history("test_rule")
        assert len(history.versions) == 2
        assert len(history.changes) == 3  # CREATED, ACTIVATED, MODIFIED
        assert history.changes[-1].change_type == ChangeType.MODIFIED
        assert history.changes[-1].from_version == "1.0.0"
        assert history.changes[-1].to_version == "1.1.0"
    
    def test_duplicate_version_raises_error(self):
        """Test that creating a duplicate version raises ValueError."""
        manager = RuleVersionManager()
        
        content = json.dumps({"rule_id": "test", "priority": 1})
        manager.create_rule_version(
            rule_id="test_rule",
            version_number="1.0.0",
            rule_content=content,
            created_by="admin"
        )
        
        with pytest.raises(ValueError, match="Version 1.0.0 already exists"):
            manager.create_rule_version(
                rule_id="test_rule",
                version_number="1.0.0",
                rule_content=content,
                created_by="admin"
            )
    
    def test_activate_version(self):
        """Test activating a specific version."""
        manager = RuleVersionManager()
        
        # Create two versions
        content = json.dumps({"rule_id": "test", "priority": 1})
        manager.create_rule_version("test_rule", "1.0.0", content, "admin")
        manager.create_rule_version("test_rule", "1.1.0", content, "admin")
        
        # Activate version 1.1.0
        activated = manager.activate_version("test_rule", "1.1.0", "admin")
        
        assert activated.version_number == "1.1.0"
        assert activated.is_active is True
        
        # Check that other versions are deactivated
        history = manager.get_version_history("test_rule")
        version1 = history.get_version("1.0.0")
        assert version1.is_active is False
        
        # Check current version is updated
        assert history.current_version == "1.1.0"
        
        # Check change was recorded
        assert history.changes[-1].change_type == ChangeType.ACTIVATED
    
    def test_activate_nonexistent_version_raises_error(self):
        """Test that activating a nonexistent version raises ValueError."""
        manager = RuleVersionManager()
        
        content = json.dumps({"rule_id": "test", "priority": 1})
        manager.create_rule_version("test_rule", "1.0.0", content, "admin")
        
        with pytest.raises(ValueError, match="Version 2.0.0 not found"):
            manager.activate_version("test_rule", "2.0.0", "admin")
    
    def test_deprecate_version(self):
        """Test deprecating a specific version."""
        manager = RuleVersionManager()
        
        content = json.dumps({"rule_id": "test", "priority": 1})
        manager.create_rule_version("test_rule", "1.0.0", content, "admin")
        
        # Deprecate the version
        deprecated = manager.deprecate_version(
            rule_id="test_rule",
            version_number="1.0.0",
            deprecated_by="admin",
            reason="Security vulnerability"
        )
        
        assert deprecated.metadata["deprecated"] is True
        assert deprecated.metadata["deprecated_by"] == "admin"
        assert deprecated.metadata["deprecation_reason"] == "Security vulnerability"
        assert "deprecated_at" in deprecated.metadata
        
        # Check change was recorded
        history = manager.get_version_history("test_rule")
        assert history.changes[-1].change_type == ChangeType.DEPRECATED
    
    def test_compare_versions(self):
        """Test comparing two versions."""
        manager = RuleVersionManager()
        
        content1 = json.dumps({"rule_id": "test", "priority": 1})
        content2 = json.dumps({"rule_id": "test", "priority": 2})
        
        manager.create_rule_version("test_rule", "1.0.0", content1, "admin")
        manager.create_rule_version("test_rule", "1.1.0", content2, "admin")
        
        comparison = manager.compare_versions("test_rule", "1.0.0", "1.1.0")
        
        assert comparison["rule_id"] == "test_rule"
        assert comparison["version1"] == "1.0.0"
        assert comparison["version2"] == "1.1.0"
        assert comparison["hash_changed"] is True
        assert comparison["content_changed"] is True
        assert "priority" in comparison["field_changes"]
        assert comparison["field_changes"]["priority"] == (1, 2)
    
    def test_compare_identical_versions(self):
        """Test comparing identical versions."""
        manager = RuleVersionManager()
        
        content = json.dumps({"rule_id": "test", "priority": 1})
        
        manager.create_rule_version("test_rule", "1.0.0", content, "admin")
        manager.create_rule_version("test_rule", "1.0.1", content, "admin")
        
        comparison = manager.compare_versions("test_rule", "1.0.0", "1.0.1")
        
        assert comparison["hash_changed"] is False
        assert comparison["content_changed"] is False
        assert comparison["field_changes"] == {}
    
    def test_get_all_active_versions(self):
        """Test retrieving all active versions."""
        manager = RuleVersionManager()
        
        content = json.dumps({"rule_id": "test", "priority": 1})
        
        # Create and activate versions for multiple rules
        manager.create_rule_version("rule1", "1.0.0", content, "admin")
        manager.activate_version("rule1", "1.0.0", "admin")
        
        manager.create_rule_version("rule2", "2.0.0", content, "admin")
        manager.activate_version("rule2", "2.0.0", "admin")
        
        manager.create_rule_version("rule3", "1.0.0", content, "admin")
        # Don't activate rule3
        
        active_versions = manager.get_all_active_versions()
        
        assert len(active_versions) == 2
        assert "rule1" in active_versions
        assert "rule2" in active_versions
        assert "rule3" not in active_versions
        assert active_versions["rule1"].version_number == "1.0.0"
        assert active_versions["rule2"].version_number == "2.0.0"
    
    def test_get_deprecated_versions(self):
        """Test retrieving all deprecated versions."""
        manager = RuleVersionManager()
        
        content = json.dumps({"rule_id": "test", "priority": 1})
        
        manager.create_rule_version("rule1", "1.0.0", content, "admin")
        manager.create_rule_version("rule1", "1.1.0", content, "admin")
        manager.create_rule_version("rule2", "1.0.0", content, "admin")
        
        # Deprecate some versions
        manager.deprecate_version("rule1", "1.0.0", "admin", "Old version")
        manager.deprecate_version("rule2", "1.0.0", "admin", "Security issue")
        
        deprecated = manager.get_deprecated_versions()
        
        assert len(deprecated) == 2
        assert all(v.metadata.get("deprecated", False) for v in deprecated)
    
    def test_verify_version_integrity(self):
        """Test verifying version integrity via hash."""
        manager = RuleVersionManager()
        
        content = json.dumps({"rule_id": "test", "priority": 1})
        manager.create_rule_version("test_rule", "1.0.0", content, "admin")
        
        # Verify integrity
        is_valid = manager.verify_version_integrity("test_rule", "1.0.0")
        assert is_valid is True
        
        # Corrupt the content
        history = manager.get_version_history("test_rule")
        version = history.get_version("1.0.0")
        version.rule_content = "corrupted content"
        
        # Verify integrity again
        is_valid = manager.verify_version_integrity("test_rule", "1.0.0")
        assert is_valid is False
    
    def test_verify_nonexistent_version(self):
        """Test verifying a nonexistent version returns False."""
        manager = RuleVersionManager()
        
        is_valid = manager.verify_version_integrity("nonexistent_rule", "1.0.0")
        assert is_valid is False


class TestIntegration:
    """Integration tests for version management workflow."""
    
    def test_complete_versioning_workflow(self):
        """Test a complete versioning workflow."""
        manager = RuleVersionManager()
        
        # 1. Create initial version
        content_v1 = json.dumps({
            "rule_id": "email_validation",
            "priority": 10,
            "pattern": "^[a-z]+@[a-z]+\\.[a-z]+$"
        })
        
        version1 = manager.create_rule_version(
            rule_id="email_validation",
            version_number="1.0.0",
            rule_content=content_v1,
            created_by="alice",
            change_description="Initial email validation rule"
        )
        
        # 2. Activate it
        manager.activate_version("email_validation", "1.0.0", "alice")
        
        # 3. Create improved version
        content_v2 = json.dumps({
            "rule_id": "email_validation",
            "priority": 10,
            "pattern": "^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$"
        })
        
        version2 = manager.create_rule_version(
            rule_id="email_validation",
            version_number="1.1.0",
            rule_content=content_v2,
            created_by="bob",
            change_description="Improved regex pattern"
        )
        
        # 4. Activate new version
        manager.activate_version("email_validation", "1.1.0", "bob")
        
        # 5. Deprecate old version
        manager.deprecate_version(
            rule_id="email_validation",
            version_number="1.0.0",
            deprecated_by="bob",
            reason="Replaced by improved pattern"
        )
        
        # 6. Verify the state
        history = manager.get_version_history("email_validation")
        
        assert len(history.versions) == 2
        assert history.current_version == "1.1.0"
        
        active_version = history.get_active_version()
        assert active_version.version_number == "1.1.0"
        assert active_version.created_by == "bob"
        
        old_version = history.get_version("1.0.0")
        assert old_version.is_active is False
        assert old_version.metadata["deprecated"] is True
        
        # 7. Compare versions
        comparison = manager.compare_versions("email_validation", "1.0.0", "1.1.0")
        assert comparison["hash_changed"] is True
        assert "pattern" in comparison["field_changes"]
        
        # 8. Verify integrity
        assert manager.verify_version_integrity("email_validation", "1.0.0") is True
        assert manager.verify_version_integrity("email_validation", "1.1.0") is True
