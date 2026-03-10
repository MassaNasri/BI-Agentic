"""
Lineage tracking using SurrealDB graph storage.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid5, NAMESPACE_URL

from .surreal_client import SurrealClient
from ..models.lineage import LineageRecord


class LineageTracker:
    def __init__(self):
        self.client = SurrealClient()
        self._ensure_schema()

    @staticmethod
    def deterministic_row_id(source_id: str, batch_id: str, dedup_key: str, stage: str) -> UUID:
        key = f"{source_id}:{batch_id}:{dedup_key}:{stage}"
        return uuid5(NAMESPACE_URL, key)

    def _ensure_schema(self) -> None:
        # Define node and edge tables for lineage graph
        self.client.query("DEFINE TABLE lineage_node SCHEMAFULL;")
        self.client.query("DEFINE TABLE lineage_edge SCHEMAFULL;")
        self.client.query("DEFINE FIELD row_id ON lineage_node TYPE string;")
        self.client.query("DEFINE FIELD source_id ON lineage_node TYPE string;")
        self.client.query("DEFINE FIELD batch_id ON lineage_node TYPE string;")
        self.client.query("DEFINE FIELD stage ON lineage_node TYPE string;")
        self.client.query("DEFINE FIELD timestamp ON lineage_node TYPE datetime;")
        self.client.query("DEFINE FIELD transformation_version ON lineage_node TYPE string;")
        self.client.query("DEFINE FIELD applied_rules ON lineage_node TYPE array;")

    def record_transformation(self, record: LineageRecord) -> Optional[Dict[str, Any]]:
        node_id = f"lineage_node:{record.row_id}"
        payload = {
            "row_id": str(record.row_id),
            "source_id": record.source_id,
            "batch_id": record.batch_id,
            "stage": record.stage,
            "timestamp": record.timestamp.isoformat(),
            "transformation_version": record.transformation_version,
            "applied_rules": record.applied_rules,
        }
        self.client.query(f"CREATE {node_id} CONTENT {json.dumps(payload)};")
        for parent in record.parent_row_ids:
            edge_payload = {
                "timestamp": record.timestamp.isoformat(),
                "stage": record.stage,
            }
            self.client.query(
                f"RELATE lineage_node:{parent} -> lineage_edge -> {node_id} CONTENT {json.dumps(edge_payload)};"
            )
        return payload

    def query_lineage(self, row_id: str) -> Dict[str, Any]:
        sql = f"""
        SELECT *,
            (SELECT <-lineage_edge<-lineage_node.* FROM lineage_node:{row_id}) AS parents,
            (SELECT ->lineage_edge->lineage_node.* FROM lineage_node:{row_id}) AS children
        FROM lineage_node:{row_id};
        """
        result = self.client.query(sql)
        return result or {}
