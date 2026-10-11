"""Proxy endpoints for report-service.

This service forwards read/report operations to voice-service.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)
VOICE_SERVICE_URL = os.getenv("VOICE_SERVICE_URL", "http://voice-service:8004").rstrip("/")


def _read_float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _read_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


PROXY_TIMEOUT = (
    _read_float_env("REPORT_PROXY_CONNECT_TIMEOUT_SECONDS", 5.0),
    _read_float_env("REPORT_PROXY_READ_TIMEOUT_SECONDS", 90.0),
)
WIDGETS_PROXY_RETRY_COUNT = _read_int_env("REPORT_WIDGETS_PROXY_RETRY_COUNT", 1)
WIDGETS_PROXY_RETRY_DELAY_SECONDS = _read_float_env("REPORT_WIDGETS_PROXY_RETRY_DELAY_SECONDS", 0.75)


def _forward_headers(request) -> dict[str, str]:
    headers: dict[str, str] = {}
    auth_header = str(request.META.get("HTTP_AUTHORIZATION", "") or "").strip()
    if auth_header:
        headers["Authorization"] = auth_header

    correlation_id = str(request.META.get("HTTP_X_CORRELATION_ID", "") or "").strip()
    if correlation_id:
        headers["X-Correlation-ID"] = correlation_id
    return headers


def _coerce_payload(data: Any) -> dict[str, Any] | list[Any] | None:
    if data is None:
        return None
    if isinstance(data, (dict, list)):
        return data
    return {"value": data}


def _proxy_request(
    *,
    request,
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    json_payload: dict[str, Any] | list[Any] | None = None,
) -> Response:
    url = f"{VOICE_SERVICE_URL}{path}"
    normalized_method = method.upper().strip()
    should_retry_widgets = (
        normalized_method == "GET"
        and path.startswith("/voice-reports/pages/")
        and path.endswith("/widgets/")
    )
    max_attempts = 1 + (WIDGETS_PROXY_RETRY_COUNT if should_retry_widgets else 0)

    upstream = None
    for attempt in range(1, max_attempts + 1):
        try:
            upstream = requests.request(
                method=normalized_method,
                url=url,
                params=params,
                json=json_payload,
                headers=_forward_headers(request),
                timeout=PROXY_TIMEOUT,
            )
            break
        except requests.Timeout as exc:
            if attempt < max_attempts:
                logger.warning(
                    "report_proxy_timeout_retry method=%s path=%s attempt=%s/%s error=%s",
                    normalized_method,
                    path,
                    attempt,
                    max_attempts,
                    exc,
                )
                time.sleep(WIDGETS_PROXY_RETRY_DELAY_SECONDS)
                continue
            logger.warning("report_proxy_request_failed method=%s path=%s error=%s", method, path, exc)
        except requests.RequestException as exc:
            logger.warning("report_proxy_request_failed method=%s path=%s error=%s", method, path, exc)
            break

    if upstream is None:
        return Response(
            {"success": False, "error": "voice_service_unavailable"},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        body: Any = upstream.json() if upstream.content else {}
    except ValueError:
        body = {"success": False, "error": "invalid_voice_service_response"}

    return Response(body, status=upstream.status_code)


class WorkspaceDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return _proxy_request(
            request=request,
            method="GET",
            path="/voice-reports/dashboard/",
            params=dict(request.query_params),
        )


class DashboardStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return _proxy_request(
            request=request,
            method="GET",
            path="/voice-reports/dashboard/stats/",
            params=dict(request.query_params),
        )


class ReportListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return _proxy_request(
            request=request,
            method="GET",
            path="/voice-reports/reports/",
            params=dict(request.query_params),
        )


class SQLEditView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, report_id):
        return _proxy_request(
            request=request,
            method="PUT",
            path=f"/voice-reports/{report_id}/sql/",
            json_payload=_coerce_payload(request.data),
        )

    def patch(self, request, report_id):
        return _proxy_request(
            request=request,
            method="PATCH",
            path=f"/voice-reports/{report_id}/sql/",
            json_payload=_coerce_payload(request.data),
        )

    def post(self, request, report_id):
        return _proxy_request(
            request=request,
            method="POST",
            path=f"/voice-reports/{report_id}/sql/",
            json_payload=_coerce_payload(request.data),
        )


class AITraceDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, report_id):
        return _proxy_request(
            request=request,
            method="GET",
            path=f"/voice-reports/{report_id}/ai-trace/",
            params=dict(request.query_params),
        )


class ReportChartTypeCapabilitiesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, report_id):
        return _proxy_request(
            request=request,
            method="GET",
            path=f"/voice-reports/{report_id}/chart-types/capabilities/",
            params=dict(request.query_params),
        )


class ReportChartTypeSwitchView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, report_id):
        return _proxy_request(
            request=request,
            method="POST",
            path=f"/voice-reports/{report_id}/chart-types/switch/",
            json_payload=_coerce_payload(request.data),
        )


class ReportDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, report_id):
        return _proxy_request(
            request=request,
            method="GET",
            path=f"/voice-reports/{report_id}/",
            params=dict(request.query_params),
        )

    def delete(self, request, report_id):
        return _proxy_request(
            request=request,
            method="DELETE",
            path=f"/voice-reports/{report_id}/",
        )


class DashboardPageListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return _proxy_request(
            request=request,
            method="GET",
            path="/voice-reports/pages/",
            params=dict(request.query_params),
        )

    def post(self, request):
        return _proxy_request(
            request=request,
            method="POST",
            path="/voice-reports/pages/",
            json_payload=_coerce_payload(request.data),
        )


class DashboardPageReorderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return _proxy_request(
            request=request,
            method="POST",
            path="/voice-reports/pages/reorder/",
            json_payload=_coerce_payload(request.data),
        )


class DashboardPageDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, page_id):
        return _proxy_request(
            request=request,
            method="GET",
            path=f"/voice-reports/pages/{page_id}/",
            params=dict(request.query_params),
        )

    def patch(self, request, page_id):
        return _proxy_request(
            request=request,
            method="PATCH",
            path=f"/voice-reports/pages/{page_id}/",
            json_payload=_coerce_payload(request.data),
        )

    def delete(self, request, page_id):
        return _proxy_request(
            request=request,
            method="DELETE",
            path=f"/voice-reports/pages/{page_id}/",
        )


class DashboardPageWidgetListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, page_id):
        return _proxy_request(
            request=request,
            method="GET",
            path=f"/voice-reports/pages/{page_id}/widgets/",
            params=dict(request.query_params),
        )

    def post(self, request, page_id):
        return _proxy_request(
            request=request,
            method="POST",
            path=f"/voice-reports/pages/{page_id}/widgets/",
            json_payload=_coerce_payload(request.data),
        )


class DashboardWidgetDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, widget_id):
        return _proxy_request(
            request=request,
            method="PATCH",
            path=f"/voice-reports/widgets/{widget_id}/",
            json_payload=_coerce_payload(request.data),
        )

    def delete(self, request, widget_id):
        return _proxy_request(
            request=request,
            method="DELETE",
            path=f"/voice-reports/widgets/{widget_id}/",
        )


class DashboardWidgetBatchUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        return _proxy_request(
            request=request,
            method="POST",
            path="/voice-reports/widgets/batch-layout/",
            json_payload=_coerce_payload(request.data),
        )


class HealthCheckView(APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        return _proxy_request(
            request=request,
            method="GET",
            path="/voice-reports/health/",
        )
