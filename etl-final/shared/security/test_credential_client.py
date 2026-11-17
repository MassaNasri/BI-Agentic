from types import SimpleNamespace
from uuid import uuid4

import pytest

from bi_platform_shared.credential_crypto import CredentialCryptoError, encrypt_credential
from shared.connectors import ConnectorError
from shared.security.credential_client import resolve_source_execution


def _reference():
    return {
        "source_id": str(uuid4()), "workspace_id": 7, "dataset_id": "31",
        "job_id": str(uuid4()), "credential_id": str(uuid4()), "credential_version": 2,
    }


def test_authorized_resolution_decrypts_only_in_memory(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_SECRET_KEY", "test-key-with-at-least-thirty-two-characters")
    monkeypatch.setenv("CREDENTIAL_RESOLVER_API_KEY", "test-resolver-key-with-at-least-thirty-two-characters")
    key_version, ciphertext = encrypt_credential("private-password")
    reference = _reference()
    calls = []
    def post(url, *, json, headers, timeout):
        calls.append((url, json, headers, timeout))
        return SimpleNamespace(status_code=200, json=lambda: {"data": {
            **reference, "key_version": key_version, "ciphertext": ciphertext,
            "engine": "postgres", "connection_metadata": {"host": "db.example"},
            "transport": "direct_secure_internet", "configuration_version": 3,
        }})
    monkeypatch.setattr("shared.security.credential_client.requests.post", post)
    engine, configuration, transport, version = resolve_source_execution(reference, service="etl-extractor")
    assert (engine, transport, version) == ("postgres", "direct_secure_internet", 3)
    assert configuration["password"] == "private-password"
    assert "private-password" not in str(calls)
    assert "ciphertext" not in str(calls)


def test_malformed_or_mismatched_resolution_fails_safely(monkeypatch):
    monkeypatch.setenv("CREDENTIAL_RESOLVER_API_KEY", "test-resolver-key-with-at-least-thirty-two-characters")
    reference = _reference()
    monkeypatch.setattr("shared.security.credential_client.requests.post", lambda *args, **kwargs:
                        SimpleNamespace(status_code=200, json=lambda: {"data": {
                            **reference, "workspace_id": 8, "key_version": "v1", "ciphertext": "bad",
                            "engine": "postgres", "connection_metadata": {},
                            "transport": "direct_secure_internet", "configuration_version": 1,
                        }}))
    with pytest.raises(ConnectorError) as caught:
        resolve_source_execution(reference, service="etl-connector")
    assert caught.value.code == "CREDENTIAL_NOT_AVAILABLE"
    with pytest.raises(ConnectorError):
        resolve_source_execution({**reference, "credential_id": "invalid"}, service="etl-extractor")
    with pytest.raises(ConnectorError):
        resolve_source_execution(reference, service="ai-service")


def test_production_encryption_requires_deployment_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CREDENTIAL_KEY_VERSION", "v1")
    monkeypatch.delenv("CREDENTIAL_SECRET_KEY", raising=False)
    monkeypatch.delenv("CREDENTIAL_SECRET_KEY_V1", raising=False)
    with pytest.raises(CredentialCryptoError) as caught:
        encrypt_credential("never-persist-me")
    assert "never-persist-me" not in str(caught.value)


def test_production_resolver_does_not_fallback_to_shared_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CREDENTIAL_RESOLVER_API_KEY", "legacy-shared-key-with-at-least-thirty-two-characters")
    monkeypatch.delenv("CREDENTIAL_RESOLVER_CONNECTOR_KEY", raising=False)
    with pytest.raises(ConnectorError) as caught:
        resolve_source_execution(_reference(), service="etl-connector")
    assert caught.value.code == "CREDENTIAL_NOT_AVAILABLE"
