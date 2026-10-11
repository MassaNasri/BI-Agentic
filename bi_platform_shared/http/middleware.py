"""Request correlation middleware shared by Django HTTP services."""

from __future__ import annotations

import re
from uuid import uuid4


_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        candidate = str(request.headers.get("X-Request-ID", "")).strip()
        request.request_id = candidate if _SAFE_REQUEST_ID.fullmatch(candidate) else str(uuid4())
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        return response
