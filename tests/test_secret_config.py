import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from bi_platform_shared.log_redaction import redact_text, redact_value, install_secret_redaction
from bi_platform_shared.security_config import validate_production_secrets


def test_placeholder_production_credentials_fail_closed():
    with pytest.raises(ImproperlyConfigured):
        validate_production_secrets('production', 'changeme', {'DB_PASSWORD': 'safe-long-password'})
    with pytest.raises(ImproperlyConfigured):
        validate_production_secrets('production', 's' * 40, {'DB_PASSWORD': 'password'})
    with pytest.raises(ImproperlyConfigured):
        validate_production_secrets('production', 's' * 40, {'METABASE_SECRET_KEY': 'short'})


def test_log_redaction_covers_urls_headers_and_known_values():
    secret = 'private-credential-value-123'
    result = redact_text(
        f'Authorization: Bearer abc.def.ghi url=postgres://reader:{secret}@db.example/x password={secret}',
        (secret,),
    )
    assert secret not in result
    assert 'abc.def.ghi' not in result
    assert 'reader:' not in result
    assert '[REDACTED]' in result


def test_nested_source_config_and_quoted_values_are_redacted():
    source = {
        'source_id': 23,
        'connection': {
            'db_password': 'tenant password with spaces',
            'provider_api_key': 'provider-key-123',
            'headers': {'Authorization': 'Bearer abc.def.ghi'},
        },
    }
    result = redact_value(source)
    assert result['source_id'] == 23
    assert result['connection']['db_password'] == '[REDACTED]'
    assert result['connection']['provider_api_key'] == '[REDACTED]'
    assert result['connection']['headers']['Authorization'] == '[REDACTED]'
    assert 'tenant password with spaces' not in redact_text(str(source))
    assert 'provider-key-123' not in redact_text(str(source))


def test_production_rejects_new_critical_credential_defaults():
    for name, value in (
        ('ADMIN_PASSWORD', 'admin'),
        ('NOTIFICATION_SERVICE_API_KEY', 'change_me_service'),
        ('AI_SERVICE_INTERNAL_API_KEY', 'dev-secret'),
        ('METABASE_ENCRYPTION_SECRET_KEY', 'short'),
        ('SURREAL_PASS', 'password'),
    ):
        with pytest.raises(ImproperlyConfigured):
            validate_production_secrets('production', 'strong-signing-key-0123456789-abcdef', {name: value})
    validate_production_secrets('development', 'dev-secret', {'DB_PASSWORD': 'password'})


def test_log_record_factory_redacts_nested_unknown_tenant_credentials():
    previous = logging.getLogRecordFactory()
    installed = getattr(logging, '_biavora_secret_factory_installed', False)
    if installed:
        del logging._biavora_secret_factory_installed
    try:
        install_secret_redaction({})
        record = logging.getLogger('secret-test').makeRecord(
            'secret-test', logging.INFO, __file__, 1, 'source=%s',
            ({'source_id': 23, 'config': {'password': 'tenant secret value'}},), None,
        )
        assert 'tenant secret value' not in record.getMessage()
        assert 'source_id' in record.getMessage()
    finally:
        logging.setLogRecordFactory(previous)
        if installed:
            logging._biavora_secret_factory_installed = True
        else:
            del logging._biavora_secret_factory_installed


def test_production_admin_login_requires_a_password_at_startup():
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update({
        'APP_ENV': 'production', 'DJANGO_SECRET_KEY': 'strong-signing-key-0123456789-abcdef',  # gitleaks:allow - deterministic settings fixture
        'DB_PASSWORD': 'strong-database-credential', 'ALLOWED_HOSTS': 'auth.example',
        'ADMIN_EMAIL': 'admin@example.test', 'ADMIN_PASSWORD': '',
        'INTERNAL_SERVICE_TOKEN': 'strong-internal-token-0123456789',
        'PYTHONPATH': str(root),
    })
    result = subprocess.run(
        [sys.executable, '-c', 'import service_config.settings'],
        cwd=root / 'services' / 'auth-service', env=environment,
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert 'ADMIN_PASSWORD is required' in result.stderr


@pytest.mark.parametrize('service', ['auth-service', 'workspace-service'])
def test_production_auth_owners_require_internal_service_token(service):
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update({
        'APP_ENV': 'production', 'DJANGO_SECRET_KEY': 'strong-signing-key-0123456789-abcdef',  # gitleaks:allow - deterministic settings fixture
        'DB_PASSWORD': 'strong-database-credential', 'ALLOWED_HOSTS': 'service.example',
        'ADMIN_EMAIL': '', 'INTERNAL_SERVICE_TOKEN': '', 'INTERNAL_API_TOKEN': '',
        'SERVICE_INTERNAL_TOKEN': '', 'PYTHONPATH': str(root),
    })
    result = subprocess.run(
        [sys.executable, '-c', 'import service_config.settings'],
        cwd=root / 'services' / service, env=environment,
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert 'internal service token is required' in result.stderr


@pytest.mark.parametrize(('auth_flag', 'api_key', 'expected'), [
    ('false', 'strong-internal-key-0123456789', 'AI internal API authentication is required'),
    ('true', '', 'AI_SERVICE_INTERNAL_API_KEY is required'),
])
def test_production_ai_internal_auth_cannot_be_disabled_or_unkeyed(auth_flag, api_key, expected):
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update({
        'APP_ENV': 'production', 'DJANGO_SECRET_KEY': 'strong-signing-key-0123456789-abcdef',  # gitleaks:allow - deterministic settings fixture
        'ALLOWED_HOSTS': 'ai.example', 'AI_SERVICE_REQUIRE_INTERNAL_AUTH': auth_flag,
        'AI_SERVICE_INTERNAL_API_KEY': api_key, 'PYTHONPATH': str(root),
    })
    result = subprocess.run(
        [sys.executable, '-c', 'import backend.settings'],
        cwd=root / 'services' / 'ai-service', env=environment,
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert expected in result.stderr


def test_production_voice_requires_ai_caller_key():
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment.update({
        'APP_ENV': 'production', 'DJANGO_SECRET_KEY': 'strong-signing-key-0123456789-abcdef',  # gitleaks:allow - deterministic settings fixture
        'DB_PASSWORD': 'strong-database-credential', 'ALLOWED_HOSTS': 'voice.example',
        'METABASE_SECRET_KEY': 'strong-metabase-signing-key-0123456789',
        'METABASE_PASSWORD': 'strong-metabase-password', 'AI_SERVICE_INTERNAL_API_KEY': '',
        'PYTHONPATH': str(root),
    })
    result = subprocess.run(
        [sys.executable, '-c', 'import service_config.settings'],
        cwd=root / 'services' / 'voice-service', env=environment,
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert 'AI_SERVICE_INTERNAL_API_KEY is required' in result.stderr
