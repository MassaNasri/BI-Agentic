"""SQLite settings used by isolated Query integration and migration tests."""

from .settings import *  # noqa: F403


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "query-foundation-a-test.sqlite3",  # noqa: F405
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# The production migration graph contains PostgreSQL-only historical data-copy
# SQL. Endpoint integration tests exercise the current ORM schema directly;
# production migration checks continue to run against the real graph.
MIGRATION_MODULES = {"database": None}

