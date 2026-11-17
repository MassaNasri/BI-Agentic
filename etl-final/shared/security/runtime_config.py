"""Deployment profile validation for ETL Django services."""

from dataclasses import dataclass
import os
import sys

from django.core.exceptions import ImproperlyConfigured
from bi_platform_shared.secret_delivery import read_secret, SecretDeliveryError
from bi_platform_shared.credential_crypto import active_key_name


_PLACEHOLDERS = {"", "change-me", "change_me", "changeme", "secret", "default", "password", "admin", "test", "example", "dummy", "dev-secret", "insecure", "123456"}
_PLACEHOLDER_PREFIXES = ("change_me", "change-me", "replace-with", "django-insecure", "example-", "dummy-", "test-only", "nonproduction")


def _weak(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered in _PLACEHOLDERS or lowered.startswith(_PLACEHOLDER_PREFIXES)


@dataclass(frozen=True)
class RuntimeSecurityConfig:
    profile: str
    secret_key: str
    debug: bool
    allowed_hosts: tuple[str, ...]


def _is_test_process() -> bool:
    return "pytest" in sys.modules or any(value in {"test", "pytest"} for value in sys.argv)


def load_runtime_security(service_name: str, *, require_credential_key: bool = False) -> RuntimeSecurityConfig:
    profile = os.getenv("APP_ENV", "").strip().lower()
    if not profile and _is_test_process():
        profile = "test"
    if profile not in {"development", "test", "production"}:
        raise ImproperlyConfigured("APP_ENV must explicitly be development, test, or production.")

    secret_key = os.getenv("DJANGO_SECRET_KEY", "").strip()
    if not secret_key and profile in {"development", "test"}:
        secret_key = f"{service_name}-{profile}-only-secret"
    if not secret_key or (profile == "production" and _weak(secret_key)) or secret_key.lower() in _PLACEHOLDERS:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY is missing or unsafe.")
    if profile == "production" and len(secret_key) < 32:
        raise ImproperlyConfigured("Production DJANGO_SECRET_KEY is too short.")

    debug = os.getenv("DJANGO_DEBUG", "false").strip().lower() in {"1", "true", "yes"}
    hosts = tuple(host.strip() for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip())
    if profile == "test" and "testserver" not in hosts:
        hosts = (*hosts, "testserver")
    if profile == "production" and (debug or not hosts or "*" in hosts):
        raise ImproperlyConfigured("Production debug and host configuration is unsafe.")
    if profile == "production" and not all(
        os.getenv(name, "").strip()
        for name in ("ETL_INTERNAL_API_KEY", "CLICKHOUSE_PASSWORD", "SURREAL_USER", "SURREAL_PASS")
    ):
        raise ImproperlyConfigured("ETL identity and datastore credentials are required in production.")
    if profile == "production":
        resolver_name = {
            "connector-service": "CREDENTIAL_RESOLVER_CONNECTOR_KEY",
            "extractor-service": "CREDENTIAL_RESOLVER_EXTRACTOR_KEY",
        }.get(service_name)
        required_names = ["ETL_INTERNAL_API_KEY", "CLICKHOUSE_PASSWORD", "SURREAL_USER", "SURREAL_PASS", active_key_name()]
        if resolver_name:
            required_names.append(resolver_name)
        redaction_environment = dict(os.environ)
        for name in required_names:
            try:
                value = read_secret(name).strip()
            except SecretDeliveryError as exc:
                raise ImproperlyConfigured(str(exc)) from exc
            if value:
                redaction_environment[name] = value
            if _weak(value) or (name in {active_key_name(), resolver_name} and len(value) < 32):
                raise ImproperlyConfigured(f"Production {name} is weak or a placeholder.")
    if require_credential_key and not read_secret(active_key_name()).strip() and profile != "test":
        raise ImproperlyConfigured("CREDENTIAL_SECRET_KEY is required for this ETL service.")
    if profile == "production":
        from shared.security.log_redaction import install_secret_redaction
        install_secret_redaction(redaction_environment)

    return RuntimeSecurityConfig(profile, secret_key, debug, hosts)
