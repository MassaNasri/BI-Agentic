import logging
import threading
import time
from collections import deque
from typing import Deque, Dict

from django.http import JsonResponse

from .routing import is_public_path

logger = logging.getLogger(__name__)


class RateLimitMiddleware:
    """
    Fixed-window-like rate limiter implemented with per-key timestamp queues.
    Keeps behavior transparent with configurable limits.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.max_requests =  int(__import__('os').getenv('GATEWAY_RATE_LIMIT_REQUESTS', '120'))
        self.window_seconds = int(__import__('os').getenv('GATEWAY_RATE_LIMIT_WINDOW_SECONDS', '60'))
        self._store: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def __call__(self, request):
        client_ip = request.META.get('REMOTE_ADDR', 'unknown')
        key = f'{client_ip}:{request.path}'
        now = time.time()

        with self._lock:
            queue = self._store.setdefault(key, deque())
            while queue and now - queue[0] > self.window_seconds:
                queue.popleft()
            if len(queue) >= self.max_requests:
                return JsonResponse(
                    {
                        'success': False,
                        'message': 'Rate limit exceeded. Please try again later.',
                    },
                    status=429,
                )
            queue.append(now)

        return self.get_response(request)


class GatewayAuthenticationMiddleware:
    """
    Gateway-level auth presence check for protected paths.
    Token verification remains owned by downstream services.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method.upper() == 'OPTIONS':
            return self.get_response(request)

        if is_public_path(request.path):
            return self.get_response(request)

        if request.path.startswith('/admin/'):
            return self.get_response(request)

        if request.path.startswith('/health/'):
            return self.get_response(request)

        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header:
            return JsonResponse(
                {
                    'success': False,
                    'message': 'Authentication credentials were not provided.',
                },
                status=401,
            )

        return self.get_response(request)


class RequestValidationMiddleware:
    """Basic gateway request validation before proxying."""

    ALLOWED_METHODS = {'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method.upper() not in self.ALLOWED_METHODS:
            return JsonResponse(
                {
                    'success': False,
                    'message': 'Method not allowed.',
                },
                status=405,
            )

        content_length = request.META.get('CONTENT_LENGTH')
        if content_length:
            try:
                if int(content_length) > 50 * 1024 * 1024:
                    return JsonResponse(
                        {
                            'success': False,
                            'message': 'Request payload too large.',
                        },
                        status=413,
                    )
            except ValueError:
                logger.warning('Invalid CONTENT_LENGTH value: %s', content_length)

        return self.get_response(request)
