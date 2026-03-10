"""
Data lineage models.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional
from uuid import UUID


@dataclass
class LineageRecord:
    row_id: UUID
    source_id: str
    batch_id: str
    stage: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    transformation_version: str = "unknown"
    applied_rules: List[str] = field(default_factory=list)
    parent_row_ids: List[UUID] = field(default_factory=list)
