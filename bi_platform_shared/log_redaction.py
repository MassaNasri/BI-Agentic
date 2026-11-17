"""Process-wide secret redaction for production log records."""

import logging
import re
from collections.abc import Mapping


_SENSITIVE_KEY = re.compile(r'(?i)(?:^|[_-])(?:password|passwd|pass|secret|token|api[_-]?key|authorization|credentials?|access[_-]?key|private[_-]?key)(?:$|[_-])')
_FIELD_NAME = r'[\w-]*(?:password|passwd|secret|token|api[_-]?key|authorization|credential|access[_-]?key|private[_-]?key)[\w-]*'
_QUOTED_FIELD = re.compile(rf'''(?i)(\b{_FIELD_NAME}\b["']?\s*[:=]\s*)(["'])(.*?)\2''')
_BARE_FIELD = re.compile(rf'''(?i)(\b{_FIELD_NAME}\b["']?\s*[:=]\s*)(?!["'])[^\s,"'}};]+''')
_BEARER = re.compile(r'(?i)(\bbearer\s+)[A-Za-z0-9._~+/-]+=*')
_URL_AUTH = re.compile(r'(?i)(://)[^\s/@:]+:[^\s/@]+@')


def redact_text(value, secrets=()):
    result = str(value)
    for secret in sorted((str(item) for item in secrets if item and len(str(item)) >= 8), key=len, reverse=True):
        result = result.replace(secret, '[REDACTED]')
    result = _URL_AUTH.sub(r'\1[REDACTED]@', result)
    result = _BEARER.sub(r'\1[REDACTED]', result)
    result = _QUOTED_FIELD.sub(lambda match: f'{match.group(1)}{match.group(2)}[REDACTED]{match.group(2)}', result)
    return _BARE_FIELD.sub(r'\1[REDACTED]', result)


def redact_value(value, secrets=()):
    """Redact nested logging arguments before their string representation is built."""
    if isinstance(value, Mapping):
        return {
            key: '[REDACTED]' if _SENSITIVE_KEY.search(str(key)) else redact_value(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(redact_value(item, secrets) for item in value)
    if isinstance(value, list):
        return [redact_value(item, secrets) for item in value]
    if isinstance(value, str):
        return redact_text(value, secrets)
    return value


def install_secret_redaction(environment):
    if getattr(logging, '_biavora_secret_factory_installed', False):
        return
    names = ('DJANGO_SECRET_KEY', 'DB_PASSWORD', 'INTEGRATION_DB_PASSWORD', 'CLICKHOUSE_PASSWORD', 'METABASE_PASSWORD',
             'METABASE_SECRET_KEY', 'METABASE_APP_DB_PASSWORD', 'METABASE_ENCRYPTION_SECRET_KEY',
             'CREDENTIAL_SECRET_KEY', 'OPENROUTER_API_KEY', 'OPENAI_API_KEY',
             'EMAIL_HOST_PASSWORD', 'ADMIN_PASSWORD', 'SURREAL_PASS', 'ETL_INTERNAL_API_KEY',
             'INGESTION_CALLBACK_API_KEY', 'NOTIFICATION_INTERNAL_API_KEY',
             'NOTIFICATION_SERVICE_API_KEY', 'AI_SERVICE_INTERNAL_API_KEY',
             'INTERNAL_SERVICE_TOKEN', 'INTERNAL_API_TOKEN', 'SERVICE_INTERNAL_TOKEN',
             'REDIS_PASSWORD', 'KAFKA_PASSWORD')
    secrets = tuple(environment.get(name, '') for name in names) + tuple(
        value for name, value in environment.items()
        if name.startswith(('CREDENTIAL_SECRET_KEY_V', 'CREDENTIAL_RESOLVER_'))
        and not name.endswith('_FILE')
    )
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        record.msg = redact_text(record.msg, secrets)
        record.args = redact_value(record.args, secrets)
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        record.msg = redact_text(message, secrets)
        record.args = ()
        # Exception rendering bypasses message redaction and may contain DSNs.
        record.exc_info = None
        record.stack_info = None
        return record

    logging.setLogRecordFactory(factory)
    logging._biavora_secret_factory_installed = True
