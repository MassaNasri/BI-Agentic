"""
Rule Versioning and Change Tracking
Implements versioning and change tracking for transformation rules.

Based on design.md section 7 and requirements US-6 (AC 6.4).

This module provides:
- Rule version management
- Change tracking between rule versions
- Rule history and audit trail
- Version comparison and diff capabilities

**Validates: Requirements US-6 (AC 6.4)**
"""
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set
from datetime import datetime
from uuid import UUID, uuid4
from enum import Enum
import hashlib
import json


class ChangeType(Enum):
    """Types of changes that can be made to a rule."""
    CREATED = "CREATED"
    MODIFIED = "MODIFIED"
    DEPRECATED = "DEPRECATED"
    DELETED = "DELETED"
    ACTIVATED = "ACTIVATED"
    DEACTIVATED = "DEACTIVATED"


@dataclass
class RuleVersion:
    """
    Represents a specific version of a transformation rule.
    
    Attributes:
        version_id: Unique identifier for this version
        rule_id: ID of the rule this version belongs to
        version_number: Semantic version (e.g., "1.0.0", "1.1.0", "2.0.0")
        created_at: When this version was created
        created_by: Who created this version
        rule_hash: SHA256 hash of rule content for integrity verification
        rule_content: Serialized rule definition (YAML or JSON)
        is_active: Whether this version is currently active
        change_description: Description of changes in this version
        metadata: Additional metadata
    """
    version_id: UUID = field(default_factory=uuid4)
    rule_id: str = ""
    version_number: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    created_by: str = ""
    rule_hash: str = ""
    rule_content: str = ""
    is_active: bool = True
    change_description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate version fields."""
        if not self.rule_id:
            raise ValueError("rule_id cannot be empty")
        if not self.version_number:
            raise ValueError("version_number cannot be empty")
        if not self._is_valid_semantic_version(self.version_number):
            raise ValueError(f"Invalid semantic version: {self.version_number}")
    
    @staticmethod
    def _is_valid_semantic_version(version: str) -> bool:
        """
        Validate semantic version format (MAJOR.MINOR.PATCH).
        
        Args:
            version: Version string to validate
            
        Returns:
            True if valid semantic version, False otherwise
        """
        parts = version.split('.')
        if len(parts) != 3:
            return False
        try:
            for part in parts:
                int(part)
            return True
        except ValueError:
            return False
    
    @staticmethod
    def compute_hash(rule_content: str) -> str:
        """
        Compute SHA256 hash of rule content.
        
        Args:
            rule_content: Serialized rule content
            
        Returns:
            Hexadecimal hash string
        """
        return hashlib.sha256(rule_content.encode('utf-8')).hexdigest()


@dataclass
class RuleChange:
    """
    Represents a change made to a rule.
    
    Attributes:
        change_id: Unique identifier for this change
        rule_id: ID of the rule that was changed
        from_version: Previous version number (None for creation)
        to_version: New version number
        change_type: Type of change (CREATED, MODIFIED, etc.)
        changed_at: When the change occurred
        changed_by: Who made the change
        change_description: Description of what changed
        field_changes: Specific field-level changes
        metadata: Additional metadata
    """
    change_id: UUID = field(default_factory=uuid4)
    rule_id: str = ""
    from_version: Optional[str] = None
    to_version: str = ""
    change_type: ChangeType = ChangeType.MODIFIED
    changed_at: datetime = field(default_factory=datetime.utcnow)
    changed_by: str = ""
    change_description: str = ""
    field_changes: Dict[str, tuple] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RuleVersionHistory:
    """
    Complete version history for a rule.
    
    Attributes:
        rule_id: ID of the rule
        versions: List of all versions (ordered by creation time)
        changes: List of all changes (ordered by change time)
        current_version: Currently active version number
    """
    rule_id: str
    versions: List[RuleVersion] = field(default_factory=list)
    changes: List[RuleChange] = field(default_factory=list)
    current_version: Optional[str] = None
    
    def get_version(self, version_number: str) -> Optional[RuleVersion]:
        """
        Get a specific version by version number.
        
        Args:
            version_number: Version to retrieve
            
        Returns:
            RuleVersion if found, None otherwise
        """
        for version in self.versions:
            if version.version_number == version_number:
                return version
        return None
    
    def get_active_version(self) -> Optional[RuleVersion]:
        """
        Get the currently active version.
        
        Returns:
            Active RuleVersion if exists, None otherwise
        """
        for version in self.versions:
            if version.is_active:
                return version
        return None
    
    def get_changes_between(self, from_version: str, to_version: str) -> List[RuleChange]:
        """
        Get all changes between two versions.
        
        Args:
            from_version: Starting version
            to_version: Ending version
            
        Returns:
            List of changes between versions
        """
        from_ver = self.get_version(from_version)
        to_ver = self.get_version(to_version)
        
        if not from_ver or not to_ver:
            return []
        
        # Filter changes between the two timestamps
        return [
            change for change in self.changes
            if from_ver.created_at <= change.changed_at <= to_ver.created_at
        ]


class RuleVersionManager:
    """
    Manages rule versioning and change tracking.
    
    This class provides functionality for:
    - Creating new rule versions
    - Tracking changes between versions
    - Managing version history
    - Comparing versions
    - Activating/deactivating versions
    """
    
    def __init__(self):
        """Initialize the version manager."""
        self.version_histories: Dict[str, RuleVersionHistory] = {}
    
    def create_rule_version(
        self,
        rule_id: str,
        version_number: str,
        rule_content: str,
        created_by: str,
        change_description: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> RuleVersion:
        """
        Create a new version of a rule.
        
        Args:
            rule_id: ID of the rule
            version_number: Semantic version number
            rule_content: Serialized rule content
            created_by: Who is creating this version
            change_description: Description of changes
            metadata: Additional metadata
            
        Returns:
            Created RuleVersion
            
        Raises:
            ValueError: If version already exists or is invalid
        """
        # Get or create version history
        if rule_id not in self.version_histories:
            self.version_histories[rule_id] = RuleVersionHistory(rule_id=rule_id)
        
        history = self.version_histories[rule_id]
        
        # Check if version already exists
        if history.get_version(version_number):
            raise ValueError(f"Version {version_number} already exists for rule {rule_id}")
        
        # Compute hash
        rule_hash = RuleVersion.compute_hash(rule_content)
        
        # Create version
        version = RuleVersion(
            rule_id=rule_id,
            version_number=version_number,
            created_by=created_by,
            rule_hash=rule_hash,
            rule_content=rule_content,
            is_active=False,  # Not active by default
            change_description=change_description,
            metadata=metadata or {}
        )
        
        # Add to history
        history.versions.append(version)
        history.versions.sort(key=lambda v: v.created_at)
        
        # Create change record
        previous_version = history.get_active_version()
        change_type = ChangeType.CREATED if not previous_version else ChangeType.MODIFIED
        
        change = RuleChange(
            rule_id=rule_id,
            from_version=previous_version.version_number if previous_version else None,
            to_version=version_number,
            change_type=change_type,
            changed_by=created_by,
            change_description=change_description,
            field_changes=self._detect_field_changes(
                previous_version.rule_content if previous_version else "",
                rule_content
            )
        )
        
        history.changes.append(change)
        history.changes.sort(key=lambda c: c.changed_at)
        
        return version
    
    def activate_version(
        self,
        rule_id: str,
        version_number: str,
        activated_by: str
    ) -> RuleVersion:
        """
        Activate a specific version of a rule.
        
        Deactivates all other versions and activates the specified one.
        
        Args:
            rule_id: ID of the rule
            version_number: Version to activate
            activated_by: Who is activating this version
            
        Returns:
            Activated RuleVersion
            
        Raises:
            ValueError: If rule or version not found
        """
        if rule_id not in self.version_histories:
            raise ValueError(f"Rule {rule_id} not found")
        
        history = self.version_histories[rule_id]
        version = history.get_version(version_number)
        
        if not version:
            raise ValueError(f"Version {version_number} not found for rule {rule_id}")
        
        # Deactivate all versions
        for v in history.versions:
            v.is_active = False
        
        # Activate specified version
        version.is_active = True
        history.current_version = version_number
        
        # Record change
        change = RuleChange(
            rule_id=rule_id,
            from_version=history.current_version,
            to_version=version_number,
            change_type=ChangeType.ACTIVATED,
            changed_by=activated_by,
            change_description=f"Activated version {version_number}"
        )
        
        history.changes.append(change)
        
        return version
    
    def deprecate_version(
        self,
        rule_id: str,
        version_number: str,
        deprecated_by: str,
        reason: str = ""
    ) -> RuleVersion:
        """
        Deprecate a specific version of a rule.
        
        Args:
            rule_id: ID of the rule
            version_number: Version to deprecate
            deprecated_by: Who is deprecating this version
            reason: Reason for deprecation
            
        Returns:
            Deprecated RuleVersion
            
        Raises:
            ValueError: If rule or version not found
        """
        if rule_id not in self.version_histories:
            raise ValueError(f"Rule {rule_id} not found")
        
        history = self.version_histories[rule_id]
        version = history.get_version(version_number)
        
        if not version:
            raise ValueError(f"Version {version_number} not found for rule {rule_id}")
        
        # Mark as deprecated
        version.metadata["deprecated"] = True
        version.metadata["deprecated_at"] = datetime.utcnow().isoformat()
        version.metadata["deprecated_by"] = deprecated_by
        version.metadata["deprecation_reason"] = reason
        
        # Record change
        change = RuleChange(
            rule_id=rule_id,
            from_version=version_number,
            to_version=version_number,
            change_type=ChangeType.DEPRECATED,
            changed_by=deprecated_by,
            change_description=f"Deprecated: {reason}"
        )
        
        history.changes.append(change)
        
        return version
    
    def get_version_history(self, rule_id: str) -> Optional[RuleVersionHistory]:
        """
        Get complete version history for a rule.
        
        Args:
            rule_id: ID of the rule
            
        Returns:
            RuleVersionHistory if found, None otherwise
        """
        return self.version_histories.get(rule_id)
    
    def compare_versions(
        self,
        rule_id: str,
        version1: str,
        version2: str
    ) -> Dict[str, Any]:
        """
        Compare two versions of a rule.
        
        Args:
            rule_id: ID of the rule
            version1: First version to compare
            version2: Second version to compare
            
        Returns:
            Dictionary containing comparison results
            
        Raises:
            ValueError: If rule or versions not found
        """
        if rule_id not in self.version_histories:
            raise ValueError(f"Rule {rule_id} not found")
        
        history = self.version_histories[rule_id]
        ver1 = history.get_version(version1)
        ver2 = history.get_version(version2)
        
        if not ver1:
            raise ValueError(f"Version {version1} not found")
        if not ver2:
            raise ValueError(f"Version {version2} not found")
        
        return {
            "rule_id": rule_id,
            "version1": version1,
            "version2": version2,
            "hash_changed": ver1.rule_hash != ver2.rule_hash,
            "content_changed": ver1.rule_content != ver2.rule_content,
            "field_changes": self._detect_field_changes(ver1.rule_content, ver2.rule_content),
            "time_difference": (ver2.created_at - ver1.created_at).total_seconds(),
            "created_by_same": ver1.created_by == ver2.created_by
        }
    
    def _detect_field_changes(
        self,
        old_content: str,
        new_content: str
    ) -> Dict[str, tuple]:
        """
        Detect field-level changes between two rule contents.
        
        Args:
            old_content: Previous rule content (JSON/YAML string)
            new_content: New rule content (JSON/YAML string)
            
        Returns:
            Dictionary mapping field names to (old_value, new_value) tuples
        """
        changes = {}
        
        try:
            # Try to parse as JSON
            old_data = json.loads(old_content) if old_content else {}
            new_data = json.loads(new_content) if new_content else {}
            
            # Find all keys
            all_keys = set(old_data.keys()) | set(new_data.keys())
            
            for key in all_keys:
                old_val = old_data.get(key)
                new_val = new_data.get(key)
                
                if old_val != new_val:
                    changes[key] = (old_val, new_val)
        
        except json.JSONDecodeError:
            # If not JSON, just compare as strings
            if old_content != new_content:
                changes["content"] = (old_content, new_content)
        
        return changes
    
    def get_all_active_versions(self) -> Dict[str, RuleVersion]:
        """
        Get all currently active rule versions.
        
        Returns:
            Dictionary mapping rule_id to active RuleVersion
        """
        active_versions = {}
        
        for rule_id, history in self.version_histories.items():
            active_version = history.get_active_version()
            if active_version:
                active_versions[rule_id] = active_version
        
        return active_versions
    
    def get_deprecated_versions(self) -> List[RuleVersion]:
        """
        Get all deprecated rule versions.
        
        Returns:
            List of deprecated RuleVersion objects
        """
        deprecated = []
        
        for history in self.version_histories.values():
            for version in history.versions:
                if version.metadata.get("deprecated", False):
                    deprecated.append(version)
        
        return deprecated
    
    def verify_version_integrity(self, rule_id: str, version_number: str) -> bool:
        """
        Verify the integrity of a rule version by checking its hash.
        
        Args:
            rule_id: ID of the rule
            version_number: Version to verify
            
        Returns:
            True if hash matches content, False otherwise
        """
        if rule_id not in self.version_histories:
            return False
        
        history = self.version_histories[rule_id]
        version = history.get_version(version_number)
        
        if not version:
            return False
        
        computed_hash = RuleVersion.compute_hash(version.rule_content)
        return computed_hash == version.rule_hash
