"""Exercise actual production settings without reading developer .env files."""
import os
from pathlib import Path
import secrets
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ("auth-service", "workspace-service", "subscription-service", "query-service")


def startup(service, debug="false", hosts="localhost,127.0.0.1"):
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "HOME", "USERPROFILE"}}
    env.update({
        "APP_ENV": "production", "DEBUG": debug, "ALLOWED_HOSTS": hosts,
        "CORS_ALLOWED_ORIGINS": "", "DJANGO_CORS_ALLOWED_ORIGINS": "",
        "DB_ACCESS_MODE": "migration", "BIAVORA_ALLOW_MIGRATION_ROLE": "1",
        "DB_NAME": "owner_environment_fixture", "DB_USER": "postgres",
        "DB_HOST": "127.0.0.1", "PAYMENT_MODE": "disabled",
        "PYTHONPATH": str(ROOT), "DJANGO_SETTINGS_MODULE": "service_config.settings",
    })
    for key in ("DJANGO_SECRET_KEY", "DB_PASSWORD", "INTERNAL_SERVICE_TOKEN",
                "CLICKHOUSE_PASSWORD", "ETL_INTERNAL_API_KEY", "INGESTION_CALLBACK_API_KEY",
                "CREDENTIAL_SECRET_KEY", "CREDENTIAL_RESOLVER_CONNECTOR_KEY",
                "CREDENTIAL_RESOLVER_EXTRACTOR_KEY"):
        env[key] = secrets.token_urlsafe(40)
    code = """
from unittest.mock import patch
with patch('dotenv.load_dotenv'):
    import django
    django.setup()
from django.conf import settings
assert settings.APP_ENV == 'production'
assert settings.DEBUG is False
assert settings.ALLOWED_HOSTS == ['localhost', '127.0.0.1']
assert settings.CORS_ALLOW_ALL_ORIGINS is False
assert settings.CORS_ALLOWED_ORIGINS == []
assert settings.DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql'
print('production startup accepted')
"""
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT / "services" / service,
                          env=env, capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("service", SERVICES)
def test_safe_owner_ci_fixture_initializes_real_django(service):
    result = startup(service)
    assert result.returncode == 0, result.stderr
    assert "production startup accepted" in result.stdout


@pytest.mark.parametrize("service", SERVICES)
@pytest.mark.parametrize(("debug", "hosts"), [
    ("true", "localhost,127.0.0.1"), ("false", ""), ("false", "*"),
])
def test_unsafe_production_owner_configuration_still_fails(service, debug, hosts):
    result = startup(service, debug, hosts)
    assert result.returncode != 0
    assert "Production DEBUG/ALLOWED_HOSTS configuration is unsafe." in result.stderr
