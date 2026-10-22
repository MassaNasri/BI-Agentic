"""Deterministic destination and pre-connect pinning checks."""

import socket
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from shared.connectors import ConnectorError, connector_registry
from shared.security.destination_policy import DestinationPolicyError, validate_destination
from shared.security.transport import DirectSecureInternetTransport, get_transport


def _answers(*addresses):
    return [(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 0, "", (address, 5432)) for address in addresses]


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.169.254",
    "100.64.0.1", "0.0.0.0", "224.0.0.1", "::1", "fe80::1", "fc00::1", "::",
])
def test_forbidden_addresses_are_rejected(monkeypatch, address):
    monkeypatch.delenv("ETL_APPROVED_DESTINATION_CIDRS", raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: _answers(address))
    with pytest.raises(DestinationPolicyError):
        validate_destination("customer.example", 5432)


def test_public_ipv4_ipv6_and_mixed_answer(monkeypatch):
    monkeypatch.delenv("ETL_APPROVED_DESTINATION_CIDRS", raising=False)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: _answers("8.8.8.8", "2606:4700:4700::1111"))
    assert len(validate_destination("customer.example", 5432)) == 2
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: _answers("8.8.8.8", "127.0.0.1"))
    with pytest.raises(DestinationPolicyError):
        validate_destination("customer.example", 5432)


def test_dns_capacity_exhaustion_fails_with_bounded_error(monkeypatch):
    monkeypatch.setattr("shared.security.destination_policy._DNS_SLOTS", SimpleNamespace(acquire=lambda timeout: False))
    with pytest.raises(DestinationPolicyError) as caught:
        validate_destination("customer.example", 5432)
    assert "time limit" in str(caught.value)


def test_preconnect_rebinding_rejected_before_driver(monkeypatch):
    connector = connector_registry.get("postgres")
    monkeypatch.setattr("shared.connectors.core.validate_destination", lambda *args: ("8.8.8.8",))
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: _answers("127.0.0.1"))
    driver = SimpleNamespace(connect=Mock(), extras=SimpleNamespace(RealDictCursor=object()))
    monkeypatch.setitem(sys.modules, "psycopg2", driver)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", driver.extras)
    cfg = connector.validate_configuration({
        "host": "customer.example", "port": 5432, "database": "sales",
        "username": "reader", "password": "never-log-this", "sslmode": "verify-full",
    })
    with pytest.raises(DestinationPolicyError):
        connector.connect(cfg)
    driver.connect.assert_not_called()


def test_postgres_pins_address_and_preserves_tls_hostname(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr("shared.security.transport.validate_destination", lambda *args: ("8.8.8.8",))
    driver = SimpleNamespace(connect=Mock(), extras=SimpleNamespace(RealDictCursor=object()))
    monkeypatch.setitem(sys.modules, "psycopg2", driver)
    monkeypatch.setitem(sys.modules, "psycopg2.extras", driver.extras)
    connector_registry.get("postgres").connect({
        "host": "customer.example", "port": 5432, "database": "sales", "username": "reader",
        "password": "secret", "connect_timeout": 3, "sslmode": "verify-full", "resolved_host": "1.1.1.1",
    })
    kwargs = driver.connect.call_args.kwargs
    assert kwargs["host"] == "customer.example"
    assert kwargs["hostaddr"] == "8.8.8.8"
    assert kwargs["sslmode"] == "verify-full"


def test_clickhouse_pins_address_and_preserves_tls_hostname(monkeypatch):
    import clickhouse_driver.dbapi as dbapi

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ETL_SOURCE_CLICKHOUSE_CA_FILE", "/platform/trust/ca.crt")
    monkeypatch.setattr("shared.connectors.core.validate_destination", lambda *args: ("1.1.1.1",))
    monkeypatch.setattr("shared.security.transport.validate_destination", lambda *args: ("8.8.8.8",))
    driver_connect = Mock()
    monkeypatch.setattr(dbapi, "connect", driver_connect)
    connector_registry.get("clickhouse").connect({
        "host": "customer.example", "port": 9440, "database": "sales",
        "username": "reader", "password": "secret", "connect_timeout": 3,
        "read_timeout": 10, "secure": True, "verify": True,
    })
    kwargs = driver_connect.call_args.kwargs
    assert kwargs["host"] == "8.8.8.8"
    assert kwargs["server_hostname"] == "customer.example"
    assert kwargs["secure"] is True
    assert kwargs["verify"] is True
    assert kwargs["check_hostname"] is True
    assert kwargs["ca_certs"] == "/platform/trust/ca.crt"


def test_unsupported_mode_and_unpinnable_production_engine_fail(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(DestinationPolicyError):
        get_transport("private_network")
    with pytest.raises(DestinationPolicyError):
        DirectSecureInternetTransport().before_connect({"host": "customer.example", "port": 3306}, "mysql")


@pytest.mark.parametrize("port", [0, -1, 65536, "invalid"])
def test_invalid_port_rejected_before_resolution(port):
    with pytest.raises(DestinationPolicyError):
        DirectSecureInternetTransport().before_connect({"host": "customer.example", "port": port}, "postgres")


def test_discovery_response_is_bounded(monkeypatch):
    connector = connector_registry.get("postgres")
    monkeypatch.setattr(connector, "validate_configuration", lambda config: config)
    monkeypatch.setattr(connector, "connect", lambda config: Mock())
    monkeypatch.setattr(connector, "list_schemas", lambda connection: ["public"])
    monkeypatch.setattr(connector, "list_tables", lambda connection, schema: [{"name": "x"}] * 501)
    with pytest.raises(ConnectorError) as caught:
        connector.discover({"host": "unused"})
    assert caught.value.code == "DISCOVERY_LIMIT_EXCEEDED"
