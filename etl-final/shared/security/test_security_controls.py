import os
import socket
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ETL_ROOT = Path(__file__).resolve().parents[2]
CONNECTOR_ROOT = ETL_ROOT / "connector-service" / "connector"
sys.path.insert(0, str(ETL_ROOT))
sys.path.insert(0, str(CONNECTOR_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "connector.settings")
os.environ.setdefault("APP_ENV", "test")

import django
django.setup()

from django.test import override_settings
from rest_framework import exceptions
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from shared.security.destination_policy import DestinationPolicyError, validate_destination
from shared.security.internal_auth import ETLInternalAuthentication, ETLRequestScope, record_matches_scope, require_etl_scope
from shared.security.runtime_config import load_runtime_security
from shared.security.log_redaction import redact_value
from shared.utils.credential_encryption import CredentialConfigurationError, CredentialEncryption


def _addr(ip):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (ip, 5432))]


@pytest.mark.parametrize("ip", ["127.0.0.1", "::1", "169.254.169.254", "10.0.0.8", "192.168.1.7"])
def test_unsafe_database_destinations_are_denied(monkeypatch, ip):
    monkeypatch.delenv("ETL_APPROVED_DESTINATION_CIDRS", raising=False)
    with patch("shared.security.destination_policy.socket.getaddrinfo", return_value=_addr(ip)):
        with pytest.raises(DestinationPolicyError):
            validate_destination("attacker-controlled.example", 5432)


def test_public_database_destination_is_allowed(monkeypatch):
    monkeypatch.delenv("ETL_APPROVED_DESTINATION_CIDRS", raising=False)
    with patch("shared.security.destination_policy.socket.getaddrinfo", return_value=_addr("8.8.8.8")):
        assert validate_destination("database.example", 5432) == ("8.8.8.8",)


def test_admin_cidr_can_explicitly_approve_private_destination(monkeypatch):
    monkeypatch.setenv("ETL_APPROVED_DESTINATION_CIDRS", "10.20.0.0/16")
    with patch("shared.security.destination_policy.socket.getaddrinfo", return_value=_addr("10.20.1.4")):
        assert validate_destination("approved.internal", 5432) == ("10.20.1.4",)


def test_missing_credential_encryption_key_fails_closed(monkeypatch):
    monkeypatch.delenv("CREDENTIAL_SECRET_KEY", raising=False)
    with pytest.raises(CredentialConfigurationError):
        CredentialEncryption()


@override_settings(ETL_INTERNAL_API_KEY="rotated-test-key")
def test_anonymous_internal_request_is_rejected():
    request = Request(APIRequestFactory().post("/api/upload/", {}))
    with pytest.raises(exceptions.AuthenticationFailed):
        ETLInternalAuthentication().authenticate(request)


@override_settings(ETL_INTERNAL_API_KEY="rotated-test-key")
def test_approved_internal_request_has_mandatory_scope():
    job_id = "7d429d28-e064-4d0f-b0bb-c6667a911b8f"
    raw = APIRequestFactory().post(
        "/api/upload/",
        {"workspace_id": "23", "dataset_id": "dataset-91", "ingestion_job_id": job_id},
        format="json",
        HTTP_X_INTERNAL_SERVICE="query-service",
        HTTP_X_INTERNAL_API_KEY="rotated-test-key",
    )
    request = Request(raw, parsers=[JSONParser()])
    principal, _ = ETLInternalAuthentication().authenticate(request)
    scope = require_etl_scope(request)
    assert principal.service_name == "query-service"
    assert scope.workspace_id == 23
    assert scope.dataset_id == "dataset-91"


@override_settings(ETL_INTERNAL_API_KEY="rotated-test-key")
def test_wrong_job_scope_is_rejected():
    raw = APIRequestFactory().post(
        "/api/upload/",
        {"workspace_id": "23", "dataset_id": "dataset-91", "ingestion_job_id": "wrong"},
        format="json",
        HTTP_X_INTERNAL_SERVICE="query-service",
        HTTP_X_INTERNAL_API_KEY="rotated-test-key",
    )
    request = Request(raw, parsers=[JSONParser()])
    ETLInternalAuthentication().authenticate(request)
    with pytest.raises(exceptions.ValidationError):
        require_etl_scope(request)


def test_production_rejects_insecure_runtime_configuration(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DJANGO_SECRET_KEY", "change-me")
    with pytest.raises(Exception):
        load_runtime_security("test-service")


def test_etl_nested_source_credentials_are_redacted():
    result = redact_value({'source_id': 7, 'config': {'password': 'tenant password',
                                                    'headers': {'Authorization': 'Bearer abc.def'}}})
    assert result['source_id'] == 7
    assert result['config']['password'] == '[REDACTED]'
    assert result['config']['headers']['Authorization'] == '[REDACTED]'


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [("workspace_id", 24), ("dataset_id", "dataset-92"), ("ingestion_job_id", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")],
)
def test_cross_scope_metadata_is_rejected(changed_field, changed_value):
    job_id = "7d429d28-e064-4d0f-b0bb-c6667a911b8f"
    scope = ETLRequestScope(23, "dataset-91", __import__("uuid").UUID(job_id))
    record = scope.as_message_fields()
    record[changed_field] = changed_value
    assert record_matches_scope(record, scope) is False
