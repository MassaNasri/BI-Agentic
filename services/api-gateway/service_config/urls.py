from django.urls import path, re_path

from gateway.views import ProxyView
from bi_platform_shared.http.health import liveness_view, readiness_view

urlpatterns = [
    path('health/', liveness_view, name='gateway-health'),
    path('ready/', readiness_view, name='gateway-ready'),
    re_path(r'^.*$', ProxyView.as_view(), name='gateway-proxy'),
]
