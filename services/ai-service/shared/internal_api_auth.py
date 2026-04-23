from __future__ import annotations

import os
from functools import wraps
from typing import Any, Callable

from django.http import JsonResponse


def _auth_required() -> bool:
    return str(os.getenv("AI_SERVICE_REQUIRE_INTERNAL_AUTH", "true")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _expected_secret() -> str:
    return str(os.getenv("AI_SERVICE_INTERNAL_API_KEY", "")).strip()


def require_internal_api_key(view_func: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not _auth_required():
            return view_func(request, *args, **kwargs)

        expected = _expected_secret()
        if not expected:
            return JsonResponse(
                {"error": "Internal API authentication is enabled but no shared key is configured."},
                status=503,
            )

        provided = str(request.headers.get("X-Internal-Api-Key", "")).strip()
        if provided != expected:
            return JsonResponse({"error": "Unauthorized internal API request."}, status=401)
        return view_func(request, *args, **kwargs)

    return _wrapped

