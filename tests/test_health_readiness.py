from unittest.mock import patch
from types import SimpleNamespace

from bi_platform_shared.http.health import CheckResult, evaluate_readiness
from bi_platform_shared.http.middleware import RequestIdMiddleware


def test_readiness_passes_when_all_dependencies_are_reachable():
    with patch.dict(
        "os.environ",
        {"READINESS_CHECK_DATABASE": "true", "READINESS_TCP_TARGETS": "cache:6379", "READINESS_HTTP_URLS": "http://upstream/health/"},
        clear=False,
    ):
        ready, checks = evaluate_readiness(
            database_check=lambda: CheckResult("database", True, "reachable"),
            tcp_check=lambda target: CheckResult(f"tcp:{target}", True, "reachable"),
            http_check=lambda url: CheckResult(f"http:{url}", True, "status_200"),
        )
    assert ready is True
    assert len(checks) == 3


def test_database_outage_fails_readiness_without_exception_or_secret_detail():
    with patch.dict("os.environ", {"READINESS_CHECK_DATABASE": "true", "READINESS_TCP_TARGETS": "", "READINESS_HTTP_URLS": ""}, clear=False):
        ready, checks = evaluate_readiness(
            database_check=lambda: CheckResult("database", False, "OperationalError")
        )
    assert ready is False
    assert checks == [CheckResult("database", False, "OperationalError")]


def test_tcp_dependency_outage_fails_readiness():
    with patch.dict("os.environ", {"READINESS_CHECK_DATABASE": "false", "READINESS_TCP_TARGETS": "kafka:9092", "READINESS_HTTP_URLS": ""}, clear=False):
        ready, checks = evaluate_readiness(
            tcp_check=lambda target: CheckResult(f"tcp:{target}", False, "TimeoutError")
        )
    assert ready is False
    assert checks[0].detail == "TimeoutError"


def test_http_dependency_outage_fails_readiness():
    with patch.dict("os.environ", {"READINESS_CHECK_DATABASE": "false", "READINESS_TCP_TARGETS": "", "READINESS_HTTP_URLS": "http://query-service:8006/health/"}, clear=False):
        ready, checks = evaluate_readiness(
            http_check=lambda url: CheckResult(f"http:{url}", False, "HTTPError")
        )
    assert ready is False
    assert checks[0].name.startswith("http:")


def test_request_id_middleware_preserves_a_safe_incoming_id():
    response = {}
    middleware = RequestIdMiddleware(lambda request: response)
    request = SimpleNamespace(headers={"X-Request-ID": "p0c-safe_123"})
    assert middleware(request) is response
    assert request.request_id == "p0c-safe_123"
    assert response["X-Request-ID"] == "p0c-safe_123"


def test_request_id_middleware_replaces_unsafe_input():
    response = {}
    middleware = RequestIdMiddleware(lambda request: response)
    request = SimpleNamespace(headers={"X-Request-ID": "secret value\nforged: header"})
    middleware(request)
    assert request.request_id != request.headers["X-Request-ID"]
    assert len(request.request_id) == 36
    assert response["X-Request-ID"] == request.request_id
