"""
Prometheus metrics utilities.
"""
from __future__ import annotations

import os
from typing import Optional

try:
    from prometheus_client import Counter, Histogram, Gauge, start_http_server, generate_latest, CONTENT_TYPE_LATEST
    PROM_AVAILABLE = True
except Exception:
    PROM_AVAILABLE = False


SERVICE_LABEL = ["service"]
STAGE_LABEL = ["service", "stage"]

ROWS_PROCESSED = Counter(
    "etl_rows_processed_total",
    "Total rows processed",
    STAGE_LABEL,
) if PROM_AVAILABLE else None

ERRORS_TOTAL = Counter(
    "etl_errors_total",
    "Total errors",
    STAGE_LABEL,
) if PROM_AVAILABLE else None

PROCESS_LATENCY = Histogram(
    "etl_processing_latency_seconds",
    "Processing latency in seconds",
    STAGE_LABEL,
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10),
) if PROM_AVAILABLE else None

HEALTH_STATUS = Gauge(
    "etl_service_healthy",
    "Service health status (1=healthy, 0=unhealthy)",
    SERVICE_LABEL,
) if PROM_AVAILABLE else None

SCHEMA_CONTRACT_MISS_TOTAL = Counter(
    "etl_schema_contract_miss_total",
    "Total rows received without a resolved schema contract",
    ["service", "mode"],
) if PROM_AVAILABLE else None

SCHEMA_CONTRACT_ENFORCEMENT_TOTAL = Counter(
    "etl_schema_contract_enforcement_total",
    "Schema contract enforcement actions",
    ["service", "action", "mode"],
) if PROM_AVAILABLE else None


def start_metrics_server(port: Optional[int] = None) -> None:
    if not PROM_AVAILABLE:
        return
    port = port or int(os.getenv("METRICS_PORT", "9100"))
    start_http_server(port)


def render_metrics():
    if not PROM_AVAILABLE:
        return b"", "text/plain"
    return generate_latest(), CONTENT_TYPE_LATEST
