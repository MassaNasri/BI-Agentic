"""
Idempotency Manager for ETL Pipeline
Provides deduplication and idempotent operation tracking using ClickHouse.
"""
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Any, Optional, List, Iterable, Sequence
from uuid import UUID, uuid4

from clickhouse_driver import Client
from clickhouse_driver.errors import Error as ClickHouseError

logger = logging.getLogger(__name__)


class PipelineStage(Enum):
    """Pipeline stages for tracking processing."""
    EXTRACT = "extract"
    TRANSFORM = "transform"
    LOAD = "load"


@dataclass
class IdempotencyKey:
    """
    Idempotency key for deduplication.
    
    Attributes:
        source_id: Identifier of the data source
        batch_id: Identifier of the processing batch
        row_hash: SHA256 hash of row content for deduplication
    """
    source_id: str
    batch_id: str
    row_hash: str
    
    def to_dedup_key(self) -> str:
        """
        Generate a composite deduplication key.
        
        Returns:
            String combining source_id, batch_id, and row_hash
        """
        return f"{self.source_id}:{self.batch_id}:{self.row_hash}"


@dataclass
class IdempotencyClaim:
    """
    Claim token returned by insert-first dedup claiming.
    """
    key: IdempotencyKey
    claim_row_id: UUID


class IdempotencyManager:
    """
    Manages idempotent operations using ClickHouse deduplication_log table.
    
    Provides methods to:
    - Check for duplicate rows
    - Mark rows as processed
    - Generate deduplication keys from row data
    
    Thread-safe and stateless - all state is externalized to ClickHouse.
    """
    
    def __init__(self, client: Client):
        """
        Initialize IdempotencyManager with ClickHouse client.

        Args:
            client: ClickHouse client instance
        """
        self.client = client
        self._dedup_table_ready = False
        self._ensure_dedup_table()

    def _ensure_dedup_table(self) -> bool:
        """
        Best-effort creation of deduplication_log table.

        Returns:
            True when table creation/verification succeeds, False otherwise.
        """
        if self.client is None:
            return False
        if self._dedup_table_ready:
            return True
        try:
            from .clickhouse_schemas import ClickHouseSchemaManager

            self._dedup_table_ready = ClickHouseSchemaManager(self.client).create_deduplication_log_table()
            if not self._dedup_table_ready:
                logger.warning("[Idempotency] deduplication_log table not ready; running fail-open mode")
        except Exception as exc:
            logger.warning("[Idempotency] Failed to ensure deduplication_log table: %s", exc)
            self._dedup_table_ready = False
        return self._dedup_table_ready
    
    def generate_row_hash(self, row: Dict[str, Any]) -> str:
        """
        Generate SHA256 hash of row content for deduplication.
        
        Args:
            row: Dictionary containing row data
            
        Returns:
            SHA256 hash as hexadecimal string
        """
        # Sort keys for deterministic hashing
        sorted_items = sorted(row.items())
        
        # Create string representation
        row_str = str(sorted_items)
        
        # Generate SHA256 hash
        hash_obj = hashlib.sha256(row_str.encode('utf-8'))
        return hash_obj.hexdigest()
    
    def is_duplicate(
        self,
        key: IdempotencyKey,
        stage: PipelineStage
    ) -> bool:
        """
        Check if a row has already been processed at a given stage.
        
        Args:
            key: IdempotencyKey containing source_id, batch_id, and row_hash
            stage: Pipeline stage to check (EXTRACT, TRANSFORM, LOAD)
            
        Returns:
            True if row has been processed, False otherwise
        """
        try:
            new_keys = self.filter_new_keys([key], stage)
            is_dup = len(new_keys) == 0
            if is_dup:
                logger.debug(
                    "[Idempotency] Duplicate detected: dedup_key=%s, stage=%s",
                    key.to_dedup_key(),
                    stage.value,
                )
            return is_dup
        except Exception as e:
            logger.error(f"[Idempotency] Unexpected error checking duplicate: {e}")
            return False

    def filter_new_keys(
        self,
        keys: Sequence[IdempotencyKey],
        stage: PipelineStage,
    ) -> List[IdempotencyKey]:
        """
        Batch-check dedup keys and return only keys not yet processed for stage.

        This avoids per-row SELECT queries and keeps dedup checks off FINAL.
        """
        if not keys:
            return []

        # Preserve input order but de-duplicate repeated keys inside the same batch.
        unique_by_dedup: Dict[str, IdempotencyKey] = {}
        ordered_dedup_keys: List[str] = []
        for key in keys:
            dedup_key = key.to_dedup_key()
            if dedup_key not in unique_by_dedup:
                unique_by_dedup[dedup_key] = key
                ordered_dedup_keys.append(dedup_key)

        if not ordered_dedup_keys:
            return []
        if self.client is None:
            # Fail-open for hash-only mode.
            return [unique_by_dedup[k] for k in ordered_dedup_keys]
        self._ensure_dedup_table()

        try:
            query = """
            SELECT _dedup_key
            FROM deduplication_log
            WHERE _stage = %(stage)s
              AND _dedup_key IN %(dedup_keys)s
            """
            rows = self.client.execute(
                query,
                {
                    "stage": stage.value,
                    "dedup_keys": tuple(ordered_dedup_keys),
                },
            )

            existing: set[str] = set()
            for row in rows or []:
                if isinstance(row, dict):
                    value = row.get("_dedup_key")
                elif isinstance(row, (tuple, list)) and row:
                    value = row[0]
                else:
                    value = None
                if value:
                    existing.add(str(value))

            return [unique_by_dedup[k] for k in ordered_dedup_keys if k not in existing]
        except ClickHouseError as e:
            logger.error("[Idempotency] Error batch-checking duplicates: %s", e)
            # Fail-open: if check fails, treat all rows as new to avoid blocking pipeline.
            return [unique_by_dedup[k] for k in ordered_dedup_keys]
        except Exception as e:
            logger.error("[Idempotency] Unexpected error batch-checking duplicates: %s", e)
            return [unique_by_dedup[k] for k in ordered_dedup_keys]
    
    def mark_processed(
        self,
        key: IdempotencyKey,
        stage: PipelineStage,
        row_id: Optional[UUID] = None
    ) -> bool:
        """
        Mark a row as processed at a given stage.
        
        Args:
            key: IdempotencyKey containing source_id, batch_id, and row_hash
            stage: Pipeline stage (EXTRACT, TRANSFORM, LOAD)
            row_id: Optional UUID of the processed row (generated if not provided)
            
        Returns:
            True if successfully marked, False otherwise
        """
        return self.mark_processed_batch(
            [key],
            stage,
            row_ids=[row_id] if row_id is not None else None,
        )

    def mark_processed_batch(
        self,
        keys: Sequence[IdempotencyKey],
        stage: PipelineStage,
        row_ids: Optional[Sequence[Optional[UUID]]] = None,
    ) -> bool:
        """
        Batch-mark dedup keys as processed in one ClickHouse INSERT.
        """
        if not keys:
            return True
        if self.client is None:
            logger.warning("[Idempotency] mark_processed_batch called without client")
            return False
        self._ensure_dedup_table()
        if row_ids is not None and len(row_ids) != len(keys):
            raise ValueError("row_ids length must match keys length")

        try:
            query = """
            INSERT INTO deduplication_log
            (_dedup_key, _batch_id, _stage, _processed_at, _row_id)
            VALUES
            """
            now = datetime.now(timezone.utc)
            payload = []
            for idx, key in enumerate(keys):
                row_id = row_ids[idx] if row_ids is not None else None
                if row_id is None:
                    row_id = uuid4()
                payload.append(
                    {
                        "_dedup_key": key.to_dedup_key(),
                        "_batch_id": key.batch_id,
                        "_stage": stage.value,
                        "_processed_at": now,
                        "_row_id": str(row_id),
                    }
                )

            self.client.execute(query, payload)
            logger.debug(
                "[Idempotency] Marked %s keys as processed for stage=%s",
                len(payload),
                stage.value,
            )
            return True
        except ClickHouseError as e:
            logger.error(f"[Idempotency] Error marking batch as processed: {e}")
            return False
        except Exception as e:
            logger.error(f"[Idempotency] Unexpected error marking batch as processed: {e}")
            return False

    def claim_new_keys(
        self,
        keys: Sequence[IdempotencyKey],
        stage: PipelineStage,
    ) -> List[IdempotencyClaim]:
        """
        Insert-first dedup claim to avoid read-then-write races.

        Strategy:
        1) Insert all candidate keys with unique _row_id claim tokens.
        2) Read winners via argMax(_row_id, _processed_at) per key.
        3) Keep only keys where winner claim token belongs to this caller.
        """
        if not keys:
            return []

        unique_by_dedup: Dict[str, IdempotencyKey] = {}
        ordered_dedup_keys: List[str] = []
        for key in keys:
            dedup_key = key.to_dedup_key()
            if dedup_key not in unique_by_dedup:
                unique_by_dedup[dedup_key] = key
                ordered_dedup_keys.append(dedup_key)

        if not ordered_dedup_keys:
            return []

        claims: List[IdempotencyClaim] = [
            IdempotencyClaim(key=unique_by_dedup[dedup_key], claim_row_id=uuid4())
            for dedup_key in ordered_dedup_keys
        ]

        if self.client is None:
            return claims
        self._ensure_dedup_table()

        try:
            insert_query = """
            INSERT INTO deduplication_log
            (_dedup_key, _batch_id, _stage, _processed_at, _row_id)
            VALUES
            """
            payload = []
            for claim in claims:
                payload.append(
                    {
                        "_dedup_key": claim.key.to_dedup_key(),
                        "_batch_id": claim.key.batch_id,
                        "_stage": stage.value,
                        "_processed_at": datetime.now(timezone.utc),
                        "_row_id": str(claim.claim_row_id),
                    }
                )
            self.client.execute(insert_query, payload)

            winner_query = """
            SELECT
                _dedup_key,
                argMax(_row_id, _processed_at) AS winner_row_id
            FROM deduplication_log
            WHERE _stage = %(stage)s
              AND _dedup_key IN %(dedup_keys)s
            GROUP BY _dedup_key
            """
            winner_rows = self.client.execute(
                winner_query,
                {"stage": stage.value, "dedup_keys": tuple(ordered_dedup_keys)},
            )
            winners: Dict[str, str] = {}
            for row in winner_rows or []:
                if isinstance(row, dict):
                    dedup_key = str(row.get("_dedup_key"))
                    winner_row_id = str(row.get("winner_row_id"))
                else:
                    dedup_key = str(row[0]) if len(row) > 0 else ""
                    winner_row_id = str(row[1]) if len(row) > 1 else ""
                if dedup_key:
                    winners[dedup_key] = winner_row_id

            claimed = []
            for claim in claims:
                dedup_key = claim.key.to_dedup_key()
                if winners.get(dedup_key) == str(claim.claim_row_id):
                    claimed.append(claim)
            return claimed
        except ClickHouseError as e:
            logger.error("[Idempotency] Error claiming batch keys: %s", e)
            # Fail-open to avoid dropping valid rows when dedup store is unavailable.
            return claims
        except Exception as e:
            logger.error("[Idempotency] Unexpected error claiming batch keys: %s", e)
            return claims

    def rollback_claims(self, claims: Sequence[IdempotencyClaim], stage: PipelineStage) -> bool:
        """
        Best-effort rollback of previously inserted claim rows.

        This is used when downstream side effects fail after claiming keys.
        """
        if not claims:
            return True
        if self.client is None:
            return True
        self._ensure_dedup_table()
        try:
            row_ids = tuple(str(claim.claim_row_id) for claim in claims)
            query = """
            ALTER TABLE deduplication_log
            DELETE WHERE _stage = %(stage)s AND _row_id IN %(row_ids)s
            """
            self.client.execute(query, {"stage": stage.value, "row_ids": row_ids})
            return True
        except ClickHouseError as e:
            logger.error("[Idempotency] Error rolling back claims: %s", e)
            return False
        except Exception as e:
            logger.error("[Idempotency] Unexpected error rolling back claims: %s", e)
            return False
    
    def check_and_mark(
        self,
        key: IdempotencyKey,
        stage: PipelineStage,
        row_id: Optional[UUID] = None
    ) -> bool:
        """
        Atomic check-and-mark operation.
        
        Checks if row is duplicate, and if not, marks it as processed.
        
        Args:
            key: IdempotencyKey containing source_id, batch_id, and row_hash
            stage: Pipeline stage (EXTRACT, TRANSFORM, LOAD)
            row_id: Optional UUID of the processed row
            
        Returns:
            True if row was not duplicate and successfully marked, False if duplicate
        """
        new_keys = self.filter_new_keys([key], stage)
        if not new_keys:
            return False
        return self.mark_processed_batch([key], stage, row_ids=[row_id])

    def check_and_mark_batch(
        self,
        keys: Sequence[IdempotencyKey],
        stage: PipelineStage,
    ) -> List[IdempotencyKey]:
        """
        Insert-first batch check+mark using claim tokens.

        Semantics:
        - Inserts candidate keys first.
        - Resolves per-key claim winner using latest timestamp.
        - Returns only keys claimed by this caller.
        """
        claims = self.claim_new_keys(keys, stage)
        return [claim.key for claim in claims]
    
    def get_processing_stats(
        self,
        batch_id: str,
        stage: Optional[PipelineStage] = None
    ) -> Dict[str, int]:
        """
        Get processing statistics for a batch.
        
        Args:
            batch_id: Batch identifier
            stage: Optional pipeline stage to filter by
            
        Returns:
            Dictionary with processing counts
        """
        try:
            if stage:
                query = """
                SELECT COUNT(*) as count
                FROM deduplication_log
                WHERE _batch_id = %(batch_id)s
                AND _stage = %(stage)s
                """
                params = {'batch_id': batch_id, 'stage': stage.value}
            else:
                query = """
                SELECT _stage, COUNT(*) as count
                FROM deduplication_log
                WHERE _batch_id = %(batch_id)s
                GROUP BY _stage
                """
                params = {'batch_id': batch_id}
            
            result = self.client.execute(query, params)
            
            if stage:
                return {'count': result[0][0] if result else 0}
            else:
                return {row[0]: row[1] for row in result}
                
        except Exception as e:
            logger.error(f"[Idempotency] Error getting processing stats: {e}")
            return {}
