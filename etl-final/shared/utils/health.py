"""Dependency-aware readiness view shared by ETL Django services."""

from __future__ import annotations

import os
from rest_framework.response import Response
from rest_framework.views import APIView

from shared.utils.health_checks import evaluate_tcp_readiness


class ReadyView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        ready, checks = evaluate_tcp_readiness()
        request_id = getattr(request, "correlation_id", "") or request.headers.get("X-Request-ID", "")
        payload: dict[str, object] = {
            "status": "ready" if ready else "not_ready",
            "service": os.getenv("SERVICE_NAME", "etl-service"),
            "checks": checks,
            "request_id": request_id,
        }
        if not ready:
            payload["error"] = {
                "code": "service_not_ready",
                "message": "One or more required dependencies are unavailable.",
                "request_id": request_id,
            }
        return Response(payload, status=200 if ready else 503)
