"""Critical PostgreSQL domain connection contract for runtime and migrations."""

import os
from functools import wraps

CRITICAL_DOMAINS = frozenset({"auth", "workspace", "integration", "query", "entitlement"})


def configure_domain_connection(config, domain, *, profile=None):
    if domain not in CRITICAL_DOMAINS:
        raise ValueError("Unknown critical database domain.")
    profile = profile or os.getenv("APP_ENV", "")
    mode = os.getenv("DB_ACCESS_MODE", "runtime")
    if profile == "production":
        from django.core.exceptions import ImproperlyConfigured

        if mode not in {"runtime", "migration"}:
            raise ImproperlyConfigured("DB_ACCESS_MODE is invalid.")
        if mode == "migration":
            if os.getenv("BIAVORA_ALLOW_MIGRATION_ROLE") != "1":
                raise ImproperlyConfigured("Migration database access requires an explicit deployment flag.")
        elif config["USER"] != f"biavora_{domain}_runtime":
            raise ImproperlyConfigured(f"Production {domain} requires its dedicated runtime database role.")
        if not config.get("PASSWORD"):
            raise ImproperlyConfigured(f"Production {domain} database password is required.")
        if config.get("ENGINE") != "django.db.backends.postgresql":
            raise ImproperlyConfigured("Critical production ownership requires PostgreSQL.")
        config["OPTIONS"] = {"options": f"-c search_path=biavora_{domain},public"}
    return config


class IntegrationDatabaseRouter:
    """Route Integration ORM work to its dedicated connection in production."""

    def db_for_read(self, model, **hints):
        if (os.getenv("APP_ENV") == "production"
                and os.getenv("DB_ACCESS_MODE", "runtime") == "runtime"
                and model._meta.app_label == "integration"):
            return "integration"
        return None

    db_for_write = db_for_read

    def allow_relation(self, obj1, obj2, **hints):
        # Integration and Query share one PostgreSQL cluster/database, with
        # distinct credentials. Django only stores the source UUID on Query.
        if {obj1._meta.app_label, obj2._meta.app_label} <= {"integration", "database"}:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if os.getenv("APP_ENV") != "production":
            return None
        if os.getenv("DB_ACCESS_MODE", "runtime") == "migration":
            # One migration principal and one recorder for this physical DB.
            # Runtime's Integration alias is a second login, not a second DB.
            return db == "default"
        if app_label == "integration":
            return db == "integration"
        return db != "integration"


def integration_atomic_alias():
    return "integration" if (os.getenv("APP_ENV") == "production"
                             and os.getenv("DB_ACCESS_MODE", "runtime") == "runtime") else "default"


def integration_atomic(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        from django.db import transaction
        with transaction.atomic(using=integration_atomic_alias()):
            return function(*args, **kwargs)
    return wrapped
