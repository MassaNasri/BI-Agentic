from __future__ import annotations

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import sys
from pathlib import Path
import threading

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, SERVICE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from query_api.resource_policy import (  # noqa: E402
    QueryResourcePolicy,
    QueryResourcePolicyConfigurationError,
    build_workspace_query_id,
)
from query_api.services.workspace_concurrency import (  # noqa: E402
    WorkspaceConcurrencyLimitExceeded,
    workspace_query_lease,
)


def _getter(values):
    return lambda name, default: str(values.get(name, default))


def test_safe_defaults_are_bounded_and_read_only():
    policy = QueryResourcePolicy.from_environment(_getter({}))
    settings = policy.clickhouse_settings(result_row_limit=501)

    assert settings["readonly"] == 1
    assert settings["max_execution_time"] == 30
    assert settings["max_result_rows"] == 501
    assert settings["result_overflow_mode"] == "throw"
    assert settings["max_result_bytes"] > 0
    assert settings["max_bytes_to_read"] > 0
    assert settings["max_memory_usage"] > 0


def test_invalid_or_unlimited_configuration_fails_startup_validation():
    for name, value in (
        ("QUERY_MAX_EXECUTION_SECONDS", "0"),
        ("QUERY_MAX_ROWS", "-1"),
        ("QUERY_MAX_RESULT_BYTES", "unlimited"),
    ):
        with pytest.raises(QueryResourcePolicyConfigurationError):
            QueryResourcePolicy.from_environment(_getter({name: value}))


def test_client_page_size_can_only_reduce_server_limit():
    policy = QueryResourcePolicy.from_environment(_getter({}))
    assert policy.page_options(page=1, page_size=1) == (1, 1, 0)
    assert policy.page_options(page=1, page_size=999_999)[1] == policy.max_page_size
    with pytest.raises(ValueError):
        policy.page_options(page=999_999, page_size=1)


def test_query_id_is_stable_and_workspace_scoped():
    assert build_workspace_query_id(1, "request-1") == build_workspace_query_id(1, "request-1")
    assert build_workspace_query_id(1, "request-1") != build_workspace_query_id(2, "request-1")


class _Backend:
    def __init__(self, key=123):
        self.key = key
        self.released = []

    def try_acquire(self, _workspace_id, _slots):
        return self.key

    def release(self, key):
        self.released.append(key)


def test_workspace_lease_releases_on_failure_and_rejects_capacity():
    backend = _Backend()
    with pytest.raises(RuntimeError):
        with workspace_query_lease(7, 2, backend=backend):
            raise RuntimeError("boom")
    assert backend.released == [123]

    with pytest.raises(WorkspaceConcurrencyLimitExceeded):
        with workspace_query_lease(7, 2, backend=_Backend(key=None)):
            pass


class _ConcurrentBackend:
    def __init__(self):
        self._lock = threading.Lock()
        self._active: dict[int, set[int]] = {}

    def try_acquire(self, workspace_id, slots):
        with self._lock:
            active = self._active.setdefault(workspace_id, set())
            for slot in range(slots):
                if slot not in active:
                    active.add(slot)
                    return (workspace_id, slot)
        return None

    def release(self, key):
        workspace_id, slot = key
        with self._lock:
            self._active[workspace_id].remove(slot)


def test_workspace_concurrency_cap_holds_under_overlapping_requests():
    backend = _ConcurrentBackend()
    both_acquired = threading.Barrier(3)
    release = threading.Event()

    def hold_slot():
        with workspace_query_lease(17, 2, backend=backend):
            both_acquired.wait(timeout=5)
            release.wait(timeout=5)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(hold_slot) for _ in range(2)]
        both_acquired.wait(timeout=5)
        try:
            with pytest.raises(WorkspaceConcurrencyLimitExceeded):
                with workspace_query_lease(17, 2, backend=backend):
                    pass
        finally:
            release.set()
        for future in futures:
            future.result(timeout=5)

    with workspace_query_lease(17, 2, backend=backend):
        pass
