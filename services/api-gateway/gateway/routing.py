import os
import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RouteTarget:
    service: str
    base_url: str


AUTH_SERVICE_URL = os.getenv('AUTH_SERVICE_URL', 'http://auth-service:8001').rstrip('/')
WORKSPACE_SERVICE_URL = os.getenv('WORKSPACE_SERVICE_URL', 'http://workspace-service:8002').rstrip('/')
REPORT_SERVICE_URL = os.getenv('REPORT_SERVICE_URL', 'http://report-service:8003').rstrip('/')
VOICE_SERVICE_URL = os.getenv('VOICE_SERVICE_URL', 'http://voice-service:8004').rstrip('/')
AI_SERVICE_URL = os.getenv('AI_SERVICE_URL', 'http://ai-service:8005').rstrip('/')
QUERY_SERVICE_URL = os.getenv('QUERY_SERVICE_URL', 'http://query-service:8006').rstrip('/')
VISUALIZATION_SERVICE_URL = os.getenv('VISUALIZATION_SERVICE_URL', 'http://visualization-service:8007').rstrip('/')

VOICE_EXECUTE_PATTERN = re.compile(r'^/voice-reports/\d+/execute/$')
VOICE_SQL_PATTERN = re.compile(r'^/voice-reports/\d+/sql/$')
VOICE_DETAIL_PATTERN = re.compile(r'^/voice-reports/\d+/$')


PUBLIC_PATH_PREFIXES = (
    '/auth/signup/',
    '/auth/login/',
    '/auth/verify-email/',
    '/auth/token/refresh/',
    '/workspace/accept-invite/',
)


def is_public_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES)


def resolve_target(path: str) -> Optional[RouteTarget]:
    if path.startswith('/auth/') or path.startswith('/user/'):
        return RouteTarget(service='auth-service', base_url=AUTH_SERVICE_URL)

    if path.startswith('/workspace/'):
        return RouteTarget(service='workspace-service', base_url=WORKSPACE_SERVICE_URL)

    if path.startswith('/database/') or path.startswith('/query/'):
        return RouteTarget(service='query-service', base_url=QUERY_SERVICE_URL)

    if path == '/voice-reports/upload/' or path == '/voice-reports/health/' or VOICE_EXECUTE_PATTERN.match(path):
        return RouteTarget(service='voice-service', base_url=VOICE_SERVICE_URL)

    if (
        path.startswith('/voice-reports/reports/')
        or path == '/voice-reports/dashboard/'
        or path == '/voice-reports/dashboard/stats/'
        or VOICE_SQL_PATTERN.match(path)
        or VOICE_DETAIL_PATTERN.match(path)
    ):
        return RouteTarget(service='report-service', base_url=REPORT_SERVICE_URL)

    if path.startswith('/visualization/'):
        return RouteTarget(service='visualization-service', base_url=VISUALIZATION_SERVICE_URL)

    if path.startswith('/ai/'):
        return RouteTarget(service='ai-service', base_url=AI_SERVICE_URL)

    return None
