"""Common production credential sanity checks for Django deployments."""

import os


_WEAK = {
    'password', 'admin', 'changeme', 'change-me', 'change_me', 'secret',
    '123456', 'default', 'test', 'example', 'dummy', 'dev-secret', 'insecure',
}
_PLACEHOLDER_PREFIXES = (
    'change_me', 'change-me', 'replace-with', 'django-insecure',
    'example-', 'dummy-', 'test-only', 'nonproduction',
)
_NAMES = (
    'DB_PASSWORD', 'CLICKHOUSE_PASSWORD', 'METABASE_PASSWORD', 'METABASE_SECRET_KEY',
    'METABASE_APP_DB_PASSWORD', 'METABASE_ENCRYPTION_SECRET_KEY',
    'CREDENTIAL_SECRET_KEY', 'ETL_INTERNAL_API_KEY', 'INGESTION_CALLBACK_API_KEY',
    'NOTIFICATION_INTERNAL_API_KEY', 'NOTIFICATION_SERVICE_API_KEY',
    'AI_SERVICE_INTERNAL_API_KEY', 'INTERNAL_SERVICE_TOKEN',
    'INTERNAL_API_TOKEN', 'SERVICE_INTERNAL_TOKEN',
    'OPENROUTER_API_KEY', 'OPENAI_API_KEY', 'EMAIL_HOST_PASSWORD',
    'ADMIN_PASSWORD', 'SURREAL_PASS', 'REDIS_PASSWORD', 'KAFKA_PASSWORD',
)


def validate_production_secrets(profile, django_secret, environment=None):
    if profile != 'production':
        return
    from django.core.exceptions import ImproperlyConfigured

    environment = os.environ if environment is None else environment
    if len(django_secret) < 32 or _is_weak(django_secret):
        raise ImproperlyConfigured('Production DJANGO_SECRET_KEY is weak or a placeholder.')
    for name in _NAMES:
        value = str(environment.get(name, '') or '').strip()
        if value and (_is_weak(value) or (name in {'METABASE_SECRET_KEY', 'METABASE_ENCRYPTION_SECRET_KEY', 'CREDENTIAL_SECRET_KEY'} and len(value) < 32)):
            raise ImproperlyConfigured(f'Production {name} is weak or a placeholder.')
    from .log_redaction import install_secret_redaction
    install_secret_redaction(environment)


def _is_weak(value):
    lowered = value.strip().lower()
    return lowered in _WEAK or lowered.startswith(_PLACEHOLDER_PREFIXES)
