"""Common production credential sanity checks for Django deployments."""

import os
import re
from .secret_delivery import read_secret, SecretDeliveryError


_WEAK = {
    'password', 'admin', 'changeme', 'change-me', 'change_me', 'secret',
    '123456', 'default', 'test', 'example', 'dummy', 'dev-secret', 'insecure',
}
_PLACEHOLDER_PREFIXES = (
    'change_me', 'change-me', 'replace-with', 'django-insecure',
    'example-', 'dummy-', 'test-only', 'nonproduction',
)
_NAMES = (
    'DB_PASSWORD', 'INTEGRATION_DB_PASSWORD', 'CLICKHOUSE_PASSWORD', 'METABASE_PASSWORD', 'METABASE_SECRET_KEY',
    'METABASE_APP_DB_PASSWORD', 'METABASE_ENCRYPTION_SECRET_KEY',
    'CREDENTIAL_SECRET_KEY', 'CREDENTIAL_RESOLVER_API_KEY',
    'CREDENTIAL_RESOLVER_CONNECTOR_KEY', 'CREDENTIAL_RESOLVER_EXTRACTOR_KEY',
    'CREDENTIAL_RESOLVER_CONNECTOR_KEY_PREVIOUS', 'CREDENTIAL_RESOLVER_EXTRACTOR_KEY_PREVIOUS',
    'ETL_INTERNAL_API_KEY', 'INGESTION_CALLBACK_API_KEY',
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
    redaction_environment = dict(environment)
    versioned = {
        name.removesuffix('_FILE') for name in environment
        if re.fullmatch(r'CREDENTIAL_SECRET_KEY_V[1-9][0-9]{0,3}(?:_FILE)?', name)
    }
    names = (*_NAMES, *sorted(versioned))
    for name in names:
        try:
            value = read_secret(name, environment=environment, production=True).strip()
        except SecretDeliveryError as exc:
            raise ImproperlyConfigured(str(exc)) from exc
        if value:
            redaction_environment[name] = value
        if value and (_is_weak(value) or ((name.startswith('CREDENTIAL_SECRET_KEY_V') or name in {'METABASE_SECRET_KEY', 'METABASE_ENCRYPTION_SECRET_KEY', 'CREDENTIAL_SECRET_KEY', 'CREDENTIAL_RESOLVER_API_KEY', 'CREDENTIAL_RESOLVER_CONNECTOR_KEY', 'CREDENTIAL_RESOLVER_EXTRACTOR_KEY', 'CREDENTIAL_RESOLVER_CONNECTOR_KEY_PREVIOUS', 'CREDENTIAL_RESOLVER_EXTRACTOR_KEY_PREVIOUS'}) and len(value) < 32)):
            raise ImproperlyConfigured(f'Production {name} is weak or a placeholder.')
    from .log_redaction import install_secret_redaction
    install_secret_redaction(redaction_environment)


def _is_weak(value):
    lowered = value.strip().lower()
    return lowered in _WEAK or lowered.startswith(_PLACEHOLDER_PREFIXES)
