import logging
import os

import requests
from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from bi_platform_shared.public_contract import (
    forbidden_public_metadata_keys, has_internal_error_diagnostic,
)

from .routing import resolve_target

logger = logging.getLogger(__name__)
UPSTREAM_TIMEOUT_SECONDS = int(os.getenv("GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "360"))


class HealthView(View):
    def get(self, request):
        return JsonResponse({"success": True, "service": "api-gateway"})


@method_decorator(csrf_exempt, name="dispatch")
class ProxyView(View):
    http_method_names = ["get", "post", "put", "patch", "delete", "options"]

    def dispatch(self, request, *args, **kwargs):
        path = request.path
        target = resolve_target(path)

        if not target:
            return JsonResponse(
                {
                    "success": False,
                    "message": "No upstream service route found for this path.",
                },
                status=404,
            )

        query_string = request.META.get("QUERY_STRING", "")
        target_url = f"{target.base_url}{path}"
        if query_string:
            target_url = f"{target_url}?{query_string}"

        headers = {}
        for key, value in request.headers.items():
            lower = key.lower()
            if lower in {"host", "content-length", "connection"}:
                continue
            headers[key] = value

        try:
            upstream = requests.request(
                method=request.method,
                url=target_url,
                data=request.body if request.body else None,
                headers=headers,
                timeout=UPSTREAM_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            logger.error(
                "Gateway upstream request failed path=%s target=%s error=%s",
                path,
                target.service,
                exc,
            )
            return JsonResponse(
                {
                    "success": False,
                    "message": f"Upstream service {target.service} unavailable.",
                },
                status=502,
            )

        if upstream.status_code >= 500:
            return JsonResponse(
                {"success": False, "error": {"code": "UPSTREAM_UNAVAILABLE"}}, status=502,
            )
        if upstream.content:
            try:
                payload = upstream.json()
            except ValueError:
                payload = None
            if upstream.status_code >= 400 and payload is None:
                logger.error("Gateway blocked a non-JSON upstream error path=%s target=%s", path, target.service)
                return JsonResponse(
                    {"success": False, "error": {"code": "UPSTREAM_CONTRACT_INVALID"}}, status=502,
                )
            if payload is not None and has_internal_error_diagnostic(payload):
                logger.error("Gateway blocked an unsafe upstream error path=%s target=%s", path, target.service)
                return JsonResponse(
                    {"success": False, "error": {"code": "UPSTREAM_CONTRACT_INVALID"}}, status=502,
                )
            if payload is not None and forbidden_public_metadata_keys(payload):
                logger.error("Gateway blocked an internal metadata field path=%s target=%s", path, target.service)
                return JsonResponse(
                    {"success": False, "error": {"code": "UPSTREAM_CONTRACT_INVALID"}}, status=502,
                )

        response = HttpResponse(content=upstream.content, status=upstream.status_code)

        excluded_headers = {
            "content-encoding", "transfer-encoding", "connection", "server",
            "x-powered-by",
        }
        for key, value in upstream.headers.items():
            if key.lower() in excluded_headers:
                continue
            if key.lower() == "location" and not value.startswith("/"):
                continue
            response[key] = value

        return response
