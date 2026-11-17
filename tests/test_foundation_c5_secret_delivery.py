"""External secret mounts must fail closed without exposing their contents."""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from bi_platform_shared.secret_delivery import SecretDeliveryError, read_secret
from bi_platform_shared.credential_crypto import decrypt_credential, encrypt_credential
from bi_platform_shared.security_config import validate_production_secrets


def test_secret_file_and_ambiguous_source():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "resolver"
        path.write_text("synthetic-resolver-identity\n", encoding="utf-8")
        if os.name == "posix":
            path.chmod(0o600)
        environment = {"APP_ENV": "production", "CREDENTIAL_RESOLVER_CONNECTOR_KEY_FILE": str(path)}
        assert read_secret("CREDENTIAL_RESOLVER_CONNECTOR_KEY", environment=environment) == "synthetic-resolver-identity"
        environment["CREDENTIAL_RESOLVER_CONNECTOR_KEY"] = "other-value"
        with pytest.raises(SecretDeliveryError, match="two configured sources"):
            read_secret("CREDENTIAL_RESOLVER_CONNECTOR_KEY", environment=environment)
        environment.pop("CREDENTIAL_RESOLVER_CONNECTOR_KEY")
        path.unlink()
        with pytest.raises(SecretDeliveryError, match="unavailable"):
            read_secret("CREDENTIAL_RESOLVER_CONNECTOR_KEY", environment=environment)


def test_versioned_credential_key_from_mount():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "key-v2"
        path.write_text("synthetic-version-two-key-0123456789abcdef\n", encoding="utf-8")
        if os.name == "posix":
            path.chmod(0o600)
        with patch.dict(os.environ, {
            "APP_ENV": "production", "CREDENTIAL_KEY_VERSION": "v2",
            "CREDENTIAL_SECRET_KEY_V2_FILE": str(path),
        }):
            version, ciphertext = encrypt_credential("synthetic-source-password")
            assert version == "v2"
            assert decrypt_credential(version, ciphertext) == "synthetic-source-password"


def test_production_validates_inline_versioned_key_and_integration_password():
    from django.core.exceptions import ImproperlyConfigured

    django_secret = "synthetic-django-secret-0123456789abcdef"
    with pytest.raises(ImproperlyConfigured, match="CREDENTIAL_SECRET_KEY_V2"):
        validate_production_secrets("production", django_secret, {
            "APP_ENV": "production", "CREDENTIAL_SECRET_KEY_V2": "weak",
        })
    with pytest.raises(ImproperlyConfigured, match="INTEGRATION_DB_PASSWORD"):
        validate_production_secrets("production", django_secret, {
            "APP_ENV": "production", "INTEGRATION_DB_PASSWORD": "password",
        })


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits required")
def test_world_readable_production_mount_is_rejected():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "key"
        path.write_text("synthetic-key", encoding="utf-8")
        path.chmod(0o644)
        with pytest.raises(SecretDeliveryError, match="permissions"):
            read_secret("CREDENTIAL_SECRET_KEY", environment={
                "APP_ENV": "production", "CREDENTIAL_SECRET_KEY_FILE": str(path),
            })
