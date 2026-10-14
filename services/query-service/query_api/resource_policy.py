"""Authoritative limits for product analytical queries.

The values are loaded once by Django settings so invalid production
configuration fails during service startup instead of silently becoming
unbounded.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from typing import Callable


class QueryResourcePolicyConfigurationError(ValueError):
    """Raised when a query resource limit is missing or unsafe."""


def _positive_int(
    getter: Callable[[str, str], str],
    name: str,
    default: int,
    *,
    maximum: int,
) -> int:
    raw_value = getter(name, str(default))
    try:
        value = int(str(raw_value).strip())
    except (TypeError, ValueError) as exc:
        raise QueryResourcePolicyConfigurationError(
            f"{name} must be an integer between 1 and {maximum}."
        ) from exc
    if value < 1 or value > maximum:
        raise QueryResourcePolicyConfigurationError(
            f"{name} must be between 1 and {maximum}."
        )
    return value


@dataclass(frozen=True)
class QueryResourcePolicy:
    max_execution_seconds: int
    max_rows: int
    max_result_bytes: int
    max_bytes_to_read: int
    max_memory_usage: int
    workspace_concurrency: int
    default_page_size: int
    max_page_size: int

    @classmethod
    def from_environment(
        cls,
        getter: Callable[[str, str], str] = os.getenv,
    ) -> "QueryResourcePolicy":
        policy = cls(
            max_execution_seconds=_positive_int(
                getter, "QUERY_MAX_EXECUTION_SECONDS", 30, maximum=600
            ),
            max_rows=_positive_int(getter, "QUERY_MAX_ROWS", 10_000, maximum=1_000_000),
            max_result_bytes=_positive_int(
                getter, "QUERY_MAX_RESULT_BYTES", 5_242_880, maximum=268_435_456
            ),
            max_bytes_to_read=_positive_int(
                getter, "QUERY_MAX_BYTES_TO_READ", 1_073_741_824, maximum=1_099_511_627_776
            ),
            max_memory_usage=_positive_int(
                getter, "QUERY_MAX_MEMORY_USAGE", 536_870_912, maximum=68_719_476_736
            ),
            workspace_concurrency=_positive_int(
                getter, "QUERY_WORKSPACE_CONCURRENCY", 2, maximum=64
            ),
            default_page_size=_positive_int(
                getter, "QUERY_PAGE_SIZE", 500, maximum=100_000
            ),
            max_page_size=_positive_int(
                getter, "QUERY_MAX_PAGE_SIZE", 1_000, maximum=100_000
            ),
        )
        if policy.default_page_size > policy.max_page_size:
            raise QueryResourcePolicyConfigurationError(
                "QUERY_PAGE_SIZE cannot exceed QUERY_MAX_PAGE_SIZE."
            )
        if policy.max_page_size > policy.max_rows:
            raise QueryResourcePolicyConfigurationError(
                "QUERY_MAX_PAGE_SIZE cannot exceed QUERY_MAX_ROWS."
            )
        return policy

    def page_options(self, *, page: object = None, page_size: object = None) -> tuple[int, int, int]:
        try:
            normalized_page = 1 if page in (None, "", b"") else int(page)
            requested_page_size = (
                self.default_page_size
                if page_size in (None, "", b"")
                else int(page_size)
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("page and page_size must be positive integers.") from exc
        if normalized_page < 1 or requested_page_size < 1:
            raise ValueError("page and page_size must be positive integers.")

        effective_page_size = min(requested_page_size, self.max_page_size)
        offset = (normalized_page - 1) * effective_page_size
        if offset >= self.max_rows:
            raise ValueError("Requested page exceeds the authorized result window.")
        effective_page_size = min(effective_page_size, self.max_rows - offset)
        return normalized_page, effective_page_size, offset

    def clickhouse_settings(self, *, result_row_limit: int) -> dict[str, int | str]:
        """Return ClickHouse 0.15.x-supported per-query server settings."""

        return {
            "readonly": 1,
            "max_execution_time": self.max_execution_seconds,
            "max_result_rows": max(1, min(int(result_row_limit), self.max_rows + 1)),
            "result_overflow_mode": "throw",
            "max_result_bytes": self.max_result_bytes,
            "max_bytes_to_read": self.max_bytes_to_read,
            "read_overflow_mode": "throw",
            "max_memory_usage": self.max_memory_usage,
        }


def build_workspace_query_id(workspace_id: object, request_id: object) -> str:
    """Build a non-secret, workspace-scoped ClickHouse query identifier."""

    workspace = int(workspace_id)
    request_token = str(request_id or "").strip()
    if not request_token:
        raise ValueError("request_id is required.")
    digest = hashlib.sha256(request_token.encode("utf-8")).hexdigest()[:32]
    return f"biavora-w{workspace}-{digest}"


__all__ = [
    "QueryResourcePolicy",
    "QueryResourcePolicyConfigurationError",
    "build_workspace_query_id",
]
