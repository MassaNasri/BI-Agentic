"""
Quality metrics calculation and ClickHouse persistence.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from clickhouse_driver import Client

from .clickhouse_schemas import ClickHouseSchemaManager


@dataclass
class BatchQualityMetrics:
    batch_id: str
    source_id: str
    row_count: int
    completeness_score: float
    validity_score: float
    consistency_score: float
    quality_score: float
    calculated_at: datetime = datetime.utcnow()


class QualityMetricsManager:
    def __init__(self, client: Client):
        self.client = client
        self.schema_manager = ClickHouseSchemaManager(client)
        self.schema_manager.create_quality_metrics_table()
        self.schema_manager.create_quality_anomalies_table()

    @staticmethod
    def calculate_completeness(rows: List[Dict[str, Any]]) -> float:
        if not rows:
            return 0.0
        total_fields = 0
        filled_fields = 0
        for row in rows:
            for _, value in row.items():
                total_fields += 1
                if value is not None and value != "":
                    filled_fields += 1
        if total_fields == 0:
            return 0.0
        return filled_fields / total_fields

    @staticmethod
    def calculate_validity(validity_scores: List[float]) -> float:
        if not validity_scores:
            return 0.0
        return sum(validity_scores) / len(validity_scores)

    @staticmethod
    def calculate_consistency(rows: List[Dict[str, Any]]) -> float:
        if not rows:
            return 0.0
        # Consistency as ratio of fields with stable types within batch
        field_types: Dict[str, set] = {}
        for row in rows:
            for key, value in row.items():
                field_types.setdefault(key, set()).add(type(value).__name__)
        consistent_fields = sum(1 for types in field_types.values() if len(types) == 1)
        total_fields = len(field_types)
        if total_fields == 0:
            return 0.0
        return consistent_fields / total_fields

    @staticmethod
    def calculate_overall(completeness: float, validity: float, consistency: float) -> float:
        return max(0.0, min(1.0, (completeness + validity + consistency) / 3.0))

    def compute_batch_metrics(
        self,
        batch_id: str,
        source_id: str,
        rows: List[Dict[str, Any]],
        validity_scores: List[float],
    ) -> BatchQualityMetrics:
        completeness = self.calculate_completeness(rows)
        validity = self.calculate_validity(validity_scores)
        consistency = self.calculate_consistency(rows)
        quality = self.calculate_overall(completeness, validity, consistency)
        return BatchQualityMetrics(
            batch_id=batch_id,
            source_id=source_id,
            row_count=len(rows),
            completeness_score=completeness,
            validity_score=validity,
            consistency_score=consistency,
            quality_score=quality,
            calculated_at=datetime.utcnow(),
        )

    def persist_metrics(self, metrics: BatchQualityMetrics) -> None:
        query = """
        INSERT INTO quality_metrics
        (_batch_id, _source_id, _calculated_at, _row_count,
         _completeness_score, _validity_score, _consistency_score, _quality_score)
        VALUES
        """
        self.client.execute(query, [{
            "_batch_id": metrics.batch_id,
            "_source_id": metrics.source_id,
            "_calculated_at": metrics.calculated_at,
            "_row_count": metrics.row_count,
            "_completeness_score": metrics.completeness_score,
            "_validity_score": metrics.validity_score,
            "_consistency_score": metrics.consistency_score,
            "_quality_score": metrics.quality_score,
        }])

    def detect_anomalies(self, source_id: str, metric_name: str, value: float, window: int = 20, z_threshold: float = 3.0):
        query = """
        SELECT _quality_score, _completeness_score, _validity_score, _consistency_score
        FROM quality_metrics
        WHERE _source_id = %(source_id)s
        ORDER BY _calculated_at DESC
        LIMIT %(window)s
        """
        rows = self.client.execute(query, {"source_id": source_id, "window": window})
        if not rows:
            return None

        metric_index = {
            "quality": 0,
            "completeness": 1,
            "validity": 2,
            "consistency": 3,
        }.get(metric_name)
        if metric_index is None:
            return None

        series = [r[metric_index] for r in rows if r[metric_index] is not None]
        if len(series) < 5:
            return None

        baseline = statistics.mean(series)
        stddev = statistics.pstdev(series) or 0.0
        if stddev == 0.0:
            return None
        zscore = (value - baseline) / stddev
        if abs(zscore) < z_threshold:
            return None

        anomaly_query = """
        INSERT INTO quality_anomalies
        (_batch_id, _source_id, _detected_at, _metric, _value, _baseline, _stddev, _zscore)
        VALUES
        """
        self.client.execute(anomaly_query, [{
            "_batch_id": "",
            "_source_id": source_id,
            "_detected_at": datetime.utcnow(),
            "_metric": metric_name,
            "_value": float(value),
            "_baseline": float(baseline),
            "_stddev": float(stddev),
            "_zscore": float(zscore),
        }])
        return {"metric": metric_name, "value": value, "baseline": baseline, "stddev": stddev, "zscore": zscore}
