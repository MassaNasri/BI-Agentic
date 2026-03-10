"""
Quarantine Manager for ETL Pipeline
Handles storage and retrieval of invalid rows in ClickHouse.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseError

from .clickhouse_schemas import ClickHouseSchemaManager
from .ch_identifiers import quote_table_name, sanitize_table_name

logger = logging.getLogger(__name__)


@dataclass
class QuarantineRecord:
    """
    Represents a quarantined row.
    """
    source_id: str
    batch_id: str
    quarantine_reason: str
    validation_errors: List[str]
    original_row: Dict[str, Any]
    row_id: Optional[UUID] = None
    quarantined_at: Optional[datetime] = None


class QuarantineManager:
    """
    Manages quarantined data in ClickHouse.
    """

    def __init__(self, client: Client, table_name: str = "quarantine"):
        self.client = client
        self.table_name = sanitize_table_name(table_name)
        self.quoted_table_name = quote_table_name(self.table_name)
        self.schema_manager = ClickHouseSchemaManager(client)
        self.schema_manager.create_quarantine_table(table_name=self.table_name)

    def quarantine(self, record: QuarantineRecord) -> Optional[UUID]:
        """
        Store a quarantined row.

        Returns:
            Quarantine ID if successful, None otherwise
        """
        quarantine_id = uuid4()
        row_id = record.row_id or uuid4()
        quarantined_at = record.quarantined_at or datetime.utcnow()

        payload = {
            "_quarantine_id": str(quarantine_id),
            "_row_id": str(row_id),
            "_batch_id": record.batch_id or "",
            "_source_id": record.source_id or "",
            "_quarantined_at": quarantined_at,
            "_quarantine_reason": record.quarantine_reason,
            "_validation_errors": record.validation_errors,
            "_original_row": json.dumps(record.original_row, default=str),
            "_reprocessed": False,
        }

        try:
            query = f"""
            INSERT INTO {self.quoted_table_name}
            (_quarantine_id, _row_id, _batch_id, _source_id, _quarantined_at,
             _quarantine_reason, _validation_errors, _original_row, _reprocessed)
            VALUES
            """
            self.client.execute(query, [payload])
            return quarantine_id
        except ClickHouseError as e:
            logger.error("[Quarantine] Error inserting record: %s", e)
            return None
        except Exception as e:
            logger.error("[Quarantine] Unexpected error inserting record: %s", e)
            return None

    def list_quarantined(
        self,
        limit: int = 100,
        offset: int = 0,
        source_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        include_reprocessed: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        List quarantined rows with optional filters.
        """
        where = []
        params: Dict[str, Any] = {"limit": limit, "offset": offset}

        if source_id:
            where.append("_source_id = %(source_id)s")
            params["source_id"] = source_id
        if batch_id:
            where.append("_batch_id = %(batch_id)s")
            params["batch_id"] = batch_id
        if not include_reprocessed:
            where.append("_reprocessed = false")

        where_clause = f"WHERE {' AND '.join(where)}" if where else ""

        query = f"""
        SELECT
            _quarantine_id,
            _row_id,
            _batch_id,
            _source_id,
            _quarantined_at,
            _quarantine_reason,
            _validation_errors,
            _original_row,
            _reprocessed
        FROM {self.quoted_table_name}
        {where_clause}
        ORDER BY _quarantined_at DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """

        try:
            rows = self.client.execute(query, params)
            results = []
            for row in rows:
                results.append({
                    "_quarantine_id": row[0],
                    "_row_id": row[1],
                    "_batch_id": row[2],
                    "_source_id": row[3],
                    "_quarantined_at": row[4],
                    "_quarantine_reason": row[5],
                    "_validation_errors": row[6],
                    "_original_row": row[7],
                    "_reprocessed": row[8],
                })
            return results
        except Exception as e:
            logger.error("[Quarantine] Error listing records: %s", e)
            return []

    def get_by_ids(self, quarantine_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Fetch quarantined records by IDs.
        """
        if not quarantine_ids:
            return []
        query = f"""
        SELECT
            _quarantine_id,
            _row_id,
            _batch_id,
            _source_id,
            _quarantined_at,
            _quarantine_reason,
            _validation_errors,
            _original_row,
            _reprocessed
        FROM {self.quoted_table_name}
        WHERE _quarantine_id IN %(ids)s
        """
        try:
            rows = self.client.execute(query, {"ids": tuple(quarantine_ids)})
            results = []
            for row in rows:
                results.append({
                    "_quarantine_id": row[0],
                    "_row_id": row[1],
                    "_batch_id": row[2],
                    "_source_id": row[3],
                    "_quarantined_at": row[4],
                    "_quarantine_reason": row[5],
                    "_validation_errors": row[6],
                    "_original_row": row[7],
                    "_reprocessed": row[8],
                })
            return results
        except Exception as e:
            logger.error("[Quarantine] Error fetching records: %s", e)
            return []

    def mark_reprocessed(self, quarantine_ids: List[str]) -> int:
        """
        Mark quarantined records as reprocessed.
        """
        if not quarantine_ids:
            return 0
        query = f"""
        ALTER TABLE {self.quoted_table_name}
        UPDATE _reprocessed = true
        WHERE _quarantine_id IN %(ids)s
        """
        try:
            self.client.execute(query, {"ids": tuple(quarantine_ids)})
            return len(quarantine_ids)
        except Exception as e:
            logger.error("[Quarantine] Error marking reprocessed: %s", e)
            return 0
