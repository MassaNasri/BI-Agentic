"""Distributed per-workspace query concurrency using PostgreSQL advisory locks."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import logging
import struct
from typing import Iterator

from django.db import connection

logger = logging.getLogger(__name__)


class WorkspaceConcurrencyLimitExceeded(Exception):
    pass


class WorkspaceConcurrencyUnavailable(Exception):
    pass


def _lock_key(workspace_id: int, slot: int) -> int:
    digest = hashlib.blake2b(
        f"biavora-query:{workspace_id}:{slot}".encode("utf-8"), digest_size=8
    ).digest()
    return struct.unpack(">q", digest)[0]


class PostgresWorkspaceConcurrencyBackend:
    """Connection-scoped locks recover automatically when a worker dies."""

    def try_acquire(self, workspace_id: int, slots: int) -> int | None:
        if connection.vendor != "postgresql":
            raise WorkspaceConcurrencyUnavailable(
                "Distributed query concurrency requires PostgreSQL."
            )
        try:
            with connection.cursor() as cursor:
                for slot in range(slots):
                    key = _lock_key(workspace_id, slot)
                    cursor.execute("SELECT pg_try_advisory_lock(%s)", [key])
                    if bool(cursor.fetchone()[0]):
                        return key
        except WorkspaceConcurrencyUnavailable:
            raise
        except Exception as exc:
            raise WorkspaceConcurrencyUnavailable(
                "Distributed query concurrency is unavailable."
            ) from exc
        return None

    def release(self, key: int) -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [key])
                released = bool(cursor.fetchone()[0])
        except Exception as exc:
            logger.error("query_concurrency_release_failed error_type=%s", type(exc).__name__)
            raise WorkspaceConcurrencyUnavailable(
                "Distributed query concurrency release failed."
            ) from exc
        if not released:
            logger.error("query_concurrency_release_missing")


@contextmanager
def workspace_query_lease(
    workspace_id: int,
    slots: int,
    *,
    backend: PostgresWorkspaceConcurrencyBackend | None = None,
) -> Iterator[None]:
    backend = backend or PostgresWorkspaceConcurrencyBackend()
    key = backend.try_acquire(int(workspace_id), int(slots))
    if key is None:
        raise WorkspaceConcurrencyLimitExceeded(
            "The workspace has reached its concurrent query limit."
        )
    logger.info("query_concurrency_acquired workspace_id=%s", workspace_id)
    try:
        yield
    finally:
        backend.release(key)
        logger.info("query_concurrency_released workspace_id=%s", workspace_id)


__all__ = [
    "PostgresWorkspaceConcurrencyBackend",
    "WorkspaceConcurrencyLimitExceeded",
    "WorkspaceConcurrencyUnavailable",
    "workspace_query_lease",
]
