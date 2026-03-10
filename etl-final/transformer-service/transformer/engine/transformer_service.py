"""
Transformer Service - Batch processing with dependency injection.

Integrates:
- CleaningRules (pre-cleaning)
- RulesEngine (declarative transformations)
- SchemaValidator (schema contract validation)
- Quality score calculation
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple

from shared.utils.idempotency_manager import IdempotencyManager
from shared.utils.quarantine_manager import QuarantineManager, QuarantineRecord
from shared.utils.metrics import SCHEMA_CONTRACT_ENFORCEMENT_TOTAL, SCHEMA_CONTRACT_MISS_TOTAL
from shared.utils.schema_contract_store import SchemaContractStore, NullSchemaContractStore
from shared.models import SchemaValidator, SchemaContract
from shared.models.rules_engine import RulesEngine
from shared.models.transformation_rule import (
    TransformationRule,
    TransformationResult,
    RuleExecutionContext,
)

from .cleaning_rules import CleaningRules
from .schema_contract_resolver import SchemaContractResolver

logger = logging.getLogger(__name__)


class SchemaContractMode(str, Enum):
    STRICT = "strict"
    WARN = "warn"
    QUARANTINE_ONLY = "quarantine_only"


class TransformerService:
    """
    Stateless transformer service with dependency injection.
    """

    def __init__(
        self,
        rules_engine: Any = RulesEngine,
        schema_validator: Optional[SchemaValidator] = None,
        cleaning_rules: Optional[CleaningRules] = None,
        idempotency_manager: Optional[IdempotencyManager] = None,
        quarantine_manager: Optional[QuarantineManager] = None,
        default_rules: Optional[List[TransformationRule]] = None,
        drop_invalid: bool = False,
        schema_contract_store: Optional[SchemaContractStore] = None,
    ):
        self.rules_engine = rules_engine
        stateless_mode = os.getenv("STATELESS_MODE", "false").lower() in ("1", "true", "yes")
        self.schema_validator = schema_validator or SchemaValidator(cache_schemas=not stateless_mode)
        self.schema_contract_store = schema_contract_store or NullSchemaContractStore()
        self.schema_contract_resolver = SchemaContractResolver(
            self.schema_validator,
            contract_store=self.schema_contract_store,
        )
        self.cleaning_rules = cleaning_rules or CleaningRules()
        self.idempotency_manager = idempotency_manager
        self.quarantine_manager = quarantine_manager
        self.default_rules = default_rules or []
        self.drop_invalid = drop_invalid
        self.schema_contract_mode = self._resolve_schema_contract_mode()

    def process_batch(
        self,
        messages: List[Dict[str, Any]],
        rules: Optional[List[TransformationRule]] = None,
        schema_contract: Optional[SchemaContract | Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Process a batch of extracted row messages.

        Returns:
            Tuple of (clean_messages, stats)
        """
        stats = {
            "processed": 0,
            "success": 0,
            "failed": 0,
            "invalid": 0,
            "quarantined": 0,
            "schema_contract_missing": 0,
            "warnings": [],
            "errors": [],
        }
        row_results: List[Dict[str, Any]] = []

        resolved_schema = self.schema_contract_resolver.register(None, None, schema_contract)
        effective_rules = rules if rules is not None else self.default_rules

        for message in messages:
            stats["processed"] += 1
            source = message.get("source") or message.get("source_id") or "unknown"
            row_data = message.get("data", {})

            if not row_data:
                stats["failed"] += 1
                stats["warnings"].append(f"[{source}] Empty row data")
                row_results.append({
                    "source": source,
                    "status": "failed",
                    "warnings": [f"[{source}] Empty row data"],
                    "errors": [],
                    "cleaned_row": None,
                    "transformed_row": None,
                    "clean_message": None,
                })
                continue

            cleaned_row, cleaning_warnings = self.cleaning_rules.apply_all(row_data)
            warnings = list(cleaning_warnings)
            errors: List[str] = []

            validation_result = None
            active_schema = self.schema_contract_resolver.resolve_for_message(
                message,
                fallback_contract=resolved_schema,
            )
            missing_contract = active_schema is None
            if missing_contract:
                warning = f"[{source}] Missing schema contract for schema_version={message.get('schema_version')}"
                warnings.append(warning)
                stats["schema_contract_missing"] += 1
                if SCHEMA_CONTRACT_MISS_TOTAL:
                    SCHEMA_CONTRACT_MISS_TOTAL.labels(
                        service="transformer",
                        mode=self.schema_contract_mode.value,
                    ).inc()

                if self.schema_contract_mode in {SchemaContractMode.STRICT, SchemaContractMode.QUARANTINE_ONLY}:
                    if self.quarantine_manager:
                        self._safe_quarantine(
                            QuarantineRecord(
                                source_id=source,
                                batch_id=message.get("batch_id", ""),
                                quarantine_reason="missing_schema_contract",
                                validation_errors=[warning],
                                original_row=row_data,
                            )
                        )
                        stats["quarantined"] += 1
                    if SCHEMA_CONTRACT_ENFORCEMENT_TOTAL:
                        SCHEMA_CONTRACT_ENFORCEMENT_TOTAL.labels(
                            service="transformer",
                            action="quarantine_reject",
                            mode=self.schema_contract_mode.value,
                        ).inc()
                    stats["failed"] += 1
                    stats["invalid"] += 1
                    stats["warnings"].extend(warnings)
                    row_results.append({
                        "source": source,
                        "status": "failed",
                        "warnings": warnings,
                        "errors": errors,
                        "cleaned_row": cleaned_row,
                        "transformed_row": None,
                        "clean_message": None,
                    })
                    continue

                if SCHEMA_CONTRACT_ENFORCEMENT_TOTAL:
                    SCHEMA_CONTRACT_ENFORCEMENT_TOTAL.labels(
                        service="transformer",
                        action="warn_continue",
                        mode=self.schema_contract_mode.value,
                    ).inc()

            validation_score = None
            if active_schema:
                validation_result = self.schema_validator.validate(cleaned_row, active_schema)
                validation_score = validation_result.quality_score
                if not validation_result.is_valid:
                    stats["invalid"] += 1
                    warnings.extend(validation_result.violations)
                    if self.drop_invalid:
                        stats["failed"] += 1
                        stats["warnings"].extend(warnings)
                        row_results.append({
                            "source": source,
                            "status": "failed",
                            "warnings": warnings,
                            "errors": errors,
                            "cleaned_row": cleaned_row,
                            "transformed_row": None,
                            "clean_message": None,
                        })
                        continue
                    if self.quarantine_manager:
                        self._safe_quarantine(
                            QuarantineRecord(
                                source_id=source,
                                batch_id=message.get("batch_id", ""),
                                quarantine_reason="schema_validation_failed",
                                validation_errors=validation_result.violations,
                                original_row=row_data,
                            )
                        )
                        stats["quarantined"] += 1
                    stats["failed"] += 1
                    stats["warnings"].extend(warnings)
                    row_results.append({
                        "source": source,
                        "status": "failed",
                        "warnings": warnings,
                        "errors": errors,
                        "cleaned_row": cleaned_row,
                        "transformed_row": None,
                        "clean_message": None,
                    })
                    continue

            context = self._build_context(message, active_schema)
            transformation_result = self.rules_engine.apply_rules(
                cleaned_row,
                effective_rules,
                context=context,
                track_changes=True,
            )

            warnings.extend(transformation_result.warnings)
            errors.extend(transformation_result.errors)

            if transformation_result.errors:
                if self.quarantine_manager:
                    self._safe_quarantine(
                        QuarantineRecord(
                            source_id=source,
                            batch_id=message.get("batch_id", ""),
                            quarantine_reason="transformation_errors",
                            validation_errors=transformation_result.errors,
                            original_row=row_data,
                        )
                    )
                    stats["quarantined"] += 1
                stats["failed"] += 1
                stats["warnings"].extend(warnings)
                stats["errors"].extend(errors)
                row_results.append({
                    "source": source,
                    "status": "failed",
                    "warnings": warnings,
                    "errors": errors,
                    "cleaned_row": cleaned_row,
                    "transformed_row": None,
                    "clean_message": None,
                })
                continue

            transformed_row = transformation_result.transformed_row

            if not transformed_row or all(v is None or v == "" for v in transformed_row.values()):
                stats["failed"] += 1
                warnings.append("Row empty after transformation")
                stats["warnings"].extend(warnings)
                row_results.append({
                    "source": source,
                    "status": "failed",
                    "warnings": warnings,
                    "errors": errors,
                    "cleaned_row": cleaned_row,
                    "transformed_row": None,
                    "clean_message": None,
                })
                continue

            quality_score = self._calculate_quality_score(transformation_result, validation_result)

            transformed_dedup_key = self._generate_row_hash(transformed_row)

            cleaned_at = datetime.utcnow().isoformat()
            clean_message = {
                "source": source,
                "source_id": source,
                "data": transformed_row,
                "_original_dedup_key": message.get("_dedup_key"),
                "_transformed_dedup_key": transformed_dedup_key,
                "_batch_id": message.get("batch_id"),
                "_extracted_at": message.get("_extracted_at"),
                "_cleaned_at": cleaned_at,
                "_parent_lineage_row_id": message.get("_lineage_row_id"),
                "batch_id": message.get("batch_id"),
                "cleaned_at": cleaned_at,
                "schema_version": message.get("schema_version") or "derived_unknown",
                "_schema_contract_mode": self.schema_contract_mode.value,
                "_schema_contract_missing": missing_contract,
                "_schema_contract_status": "missing_warn" if missing_contract else "validated",
                "quality_score": quality_score,
                "validation_score": validation_score,
                "warnings": warnings,
                "errors": errors,
                "_applied_rules": transformation_result.applied_rules,
            }

            if "table" in message:
                clean_message["table"] = message["table"]
            if "row_id" in message:
                clean_message["row_id"] = message["row_id"]

            row_results.append({
                "source": source,
                "status": "success",
                "warnings": warnings,
                "errors": errors,
                "cleaned_row": cleaned_row,
                "transformed_row": transformed_row,
                "clean_message": clean_message,
            })
            stats["success"] += 1
            stats["warnings"].extend(warnings)
            stats["errors"].extend(errors)

        return row_results, stats

    def _resolve_schema_contract(
        self,
        schema_contract: Optional[SchemaContract | Dict[str, Any]],
    ) -> Optional[SchemaContract]:
        # Backward-compatible wrapper kept for existing callers/tests.
        return self.schema_contract_resolver.register(None, None, schema_contract)

    def _resolve_schema_contract_mode(self) -> SchemaContractMode:
        """
        Resolve contract behavior mode from env with backward compatibility.
        """
        raw_mode = os.getenv("SCHEMA_CONTRACT_MODE", "warn").strip().lower()
        legacy_required = os.getenv("TRANSFORMER_REQUIRE_SCHEMA_CONTRACT", "false").lower() in (
            "1",
            "true",
            "yes",
        )

        if raw_mode not in {
            SchemaContractMode.STRICT.value,
            SchemaContractMode.WARN.value,
            SchemaContractMode.QUARANTINE_ONLY.value,
        }:
            raw_mode = SchemaContractMode.WARN.value

        # Legacy flag kept for compatibility: enforce strict if explicitly enabled and no explicit mode.
        if legacy_required and os.getenv("SCHEMA_CONTRACT_MODE") is None:
            raw_mode = SchemaContractMode.STRICT.value

        return SchemaContractMode(raw_mode)

    def _safe_quarantine(self, record: QuarantineRecord) -> None:
        """
        Quarantine must not fail the core transform path.
        """
        try:
            self.quarantine_manager.quarantine(record)
        except Exception as exc:
            logger.warning("Quarantine side-effect failed and was skipped: %s", exc)

    def _build_context(
        self,
        message: Dict[str, Any],
        schema_contract: Optional[SchemaContract],
    ) -> Optional[RuleExecutionContext]:
        batch_id = message.get("batch_id")
        source_id = message.get("source") or message.get("source_id")
        if not batch_id or not source_id:
            return None
        schema_version = (
            schema_contract.version
            if schema_contract
            else (message.get("schema_version") or "derived_unknown")
        )
        return RuleExecutionContext(
            batch_id=batch_id,
            source_id=source_id,
            schema_version=schema_version,
        )

    def _calculate_quality_score(
        self,
        transformation_result: TransformationResult,
        validation_result: Optional[Any],
    ) -> float:
        scores = []
        if transformation_result.quality_score is not None:
            scores.append(transformation_result.quality_score)
        if validation_result is not None:
            scores.append(validation_result.quality_score)
        if not scores:
            return 1.0
        return max(0.0, min(1.0, sum(scores) / len(scores)))

    def _generate_row_hash(self, row: Dict[str, Any]) -> str:
        if self.idempotency_manager:
            return self.idempotency_manager.generate_row_hash(row)
        # Fallback for hash generation if no IdempotencyManager is available
        import hashlib

        sorted_items = sorted(row.items())
        row_str = str(sorted_items)
        return hashlib.sha256(row_str.encode("utf-8")).hexdigest()
