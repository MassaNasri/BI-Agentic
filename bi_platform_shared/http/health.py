"""Small, dependency-aware liveness and readiness endpoints for Django services."""

from __future__ import annotations

import os
import socket
import urllib.request
from dataclasses import asdict, dataclass
from typing import Callable

from django.db import connections
from django.http import JsonResponse


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def _timeout() -> float:
    return max(0.1, min(float(os.getenv("READINESS_TIMEOUT_SECONDS", "1.5")), 10.0))


def _check_database() -> CheckResult:
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return CheckResult("database", True, "reachable")
    except Exception as exc:  # pragma: no cover - backend-specific error types
        return CheckResult("database", False, type(exc).__name__)


def _check_tcp(target: str) -> CheckResult:
    host, separator, raw_port = target.rpartition(":")
    if not separator or not host:
        return CheckResult(f"tcp:{target}", False, "invalid_target")
    try:
        with socket.create_connection((host, int(raw_port)), timeout=_timeout()):
            pass
        return CheckResult(f"tcp:{target}", True, "reachable")
    except Exception as exc:
        return CheckResult(f"tcp:{target}", False, type(exc).__name__)


def _check_http(url: str) -> CheckResult:
    try:
        with urllib.request.urlopen(url, timeout=_timeout()) as response:
            ok = 200 <= response.status < 400
            return CheckResult(f"http:{url}", ok, f"status_{response.status}")
    except Exception as exc:
        return CheckResult(f"http:{url}", False, type(exc).__name__)


def _csv_env(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


def evaluate_readiness(
    *,
    database_check: Callable[[], CheckResult] = _check_database,
    tcp_check: Callable[[str], CheckResult] = _check_tcp,
    http_check: Callable[[str], CheckResult] = _check_http,
) -> tuple[bool, list[CheckResult]]:
    checks: list[CheckResult] = []
    if os.getenv("READINESS_CHECK_DATABASE", "true").strip().lower() in {"1", "true", "yes", "on"}:
        checks.append(database_check())
    checks.extend(tcp_check(target) for target in _csv_env("READINESS_TCP_TARGETS"))
    checks.extend(http_check(url) for url in _csv_env("READINESS_HTTP_URLS"))
    return all(check.ok for check in checks), checks


def liveness_view(request):
    service = os.getenv("SERVICE_NAME", "django-service")
    return JsonResponse({"status": "alive", "service": service, "request_id": getattr(request, "request_id", "")})


def readiness_view(request):
    ready, checks = evaluate_readiness()
    request_id = getattr(request, "request_id", "")
    payload = {
        "status": "ready" if ready else "not_ready",
        "service": os.getenv("SERVICE_NAME", "django-service"),
        "checks": [asdict(check) for check in checks],
        "request_id": request_id,
    }
    if not ready:
        payload["error"] = {
            "code": "service_not_ready",
            "message": "One or more required dependencies are unavailable.",
            "request_id": request_id,
        }
    return JsonResponse(payload, status=200 if ready else 503)
