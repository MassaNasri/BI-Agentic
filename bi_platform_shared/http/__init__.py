"""Shared HTTP helpers.

Client exports are loaded lazily so dependency-light modules such as health and
request-ID middleware do not require the optional ``requests`` package merely
because Python initializes this package.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from bi_platform_shared.http.client import (
        CircuitBreakerOpenError,
        HttpClient,
        HttpClientError,
        get_default_client,
    )

__all__ = [
    "CircuitBreakerOpenError",
    "HttpClient",
    "HttpClientError",
    "get_default_client",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from bi_platform_shared.http import client

        return getattr(client, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
