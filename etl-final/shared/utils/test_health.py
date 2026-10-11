from unittest.mock import patch

from shared.utils.health_checks import evaluate_tcp_readiness


def test_etl_readiness_passes_without_configured_dependencies():
    ready, checks = evaluate_tcp_readiness("")
    assert ready is True
    assert checks == []


def test_etl_readiness_fails_on_dependency_outage():
    with patch("shared.utils.health_checks.socket.create_connection", side_effect=TimeoutError("unavailable")):
        ready, checks = evaluate_tcp_readiness("kafka:9092")
    assert ready is False
    assert checks == [{"name": "tcp:kafka:9092", "ok": False, "detail": "TimeoutError"}]
