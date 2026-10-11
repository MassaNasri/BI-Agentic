"""Deployment profile validation for ETL Django services."""

from dataclasses import dataclass
import os
import sys

from django.core.exceptions import ImproperlyConfigured


_PLACEHOLDERS = {"", "change-me", "changeme", "secret", "default", "password"}


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
    lowered_secret = secret_key.lower()
    if not secret_key or lowered_secret in _PLACEHOLDERS or any(
        marker in lowered_secret for marker in ("change_me", "change-me", "replace-with", "django-insecure")
    ):
        raise ImproperlyConfigured("DJANGO_SECRET_KEY is missing or unsafe.")

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
    if require_credential_key and not os.getenv("CREDENTIAL_SECRET_KEY", "").strip() and profile != "test":
        raise ImproperlyConfigured("CREDENTIAL_SECRET_KEY is required for this ETL service.")

    return RuntimeSecurityConfig(profile, secret_key, debug, hosts)
