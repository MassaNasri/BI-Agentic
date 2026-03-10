"""
Django middleware for correlation IDs, structured logging, and metrics.
"""
from __future__ import annotations

import time
from uuid import uuid4

from .logging_utils import set_correlation_id
from .tracing import get_tracer, set_trace_id_from_span
from .metrics import PROCESS_LATENCY, ERRORS_TOTAL


class CorrelationIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        correlation_id = request.headers.get("X-Correlation-Id") or request.headers.get("X-Correlation-ID")
        if not correlation_id:
            correlation_id = str(uuid4())
        set_correlation_id(correlation_id)
        tracer = get_tracer("django")
        if tracer:
            with tracer.start_as_current_span(f"http {request.method} {request.path}") as span:
                set_trace_id_from_span(span)
                response = self.get_response(request)
        else:
            response = self.get_response(request)
        response["X-Correlation-Id"] = correlation_id
        return response


class MetricsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.time()
        response = self.get_response(request)
        duration = time.time() - start
        if PROCESS_LATENCY:
            PROCESS_LATENCY.labels(service="django", stage=request.path).observe(duration)
        if response.status_code >= 500 and ERRORS_TOTAL:
            ERRORS_TOTAL.labels(service="django", stage=request.path).inc()
        return response
