"""
OpenTelemetry tracing utilities with Kafka propagation support.
"""
from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional, Tuple

from .logging_utils import set_trace_id

try:
    from opentelemetry import trace, propagate
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    OTEL_AVAILABLE = True
except Exception:
    OTEL_AVAILABLE = False
    trace = None
    propagate = None


def configure_tracing(service_name: str) -> None:
    if not OTEL_AVAILABLE:
        return
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317"),
        insecure=True,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def get_tracer(name: str):
    if not OTEL_AVAILABLE:
        return None
    return trace.get_tracer(name)


def inject_trace_headers(headers: Optional[List[Tuple[str, bytes]]] = None) -> List[Tuple[str, bytes]]:
    if not OTEL_AVAILABLE:
        return headers or []
    carrier: Dict[str, str] = {}
    propagate.inject(carrier)
    out = headers[:] if headers else []
    for key, value in carrier.items():
        out.append((key, value.encode("utf-8")))
    return out


def extract_trace_headers(headers: Optional[Iterable[Tuple[str, bytes]]]):
    if not OTEL_AVAILABLE:
        return None
    carrier: Dict[str, str] = {}
    if headers:
        for key, value in headers:
            try:
                carrier[key] = value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else str(value)
            except Exception:
                continue
    ctx = propagate.extract(carrier)
    return ctx


def set_trace_id_from_span(span) -> None:
    if not OTEL_AVAILABLE or span is None:
        return
    try:
        trace_id = format(span.get_span_context().trace_id, "032x")
        set_trace_id(trace_id)
    except Exception:
        return
