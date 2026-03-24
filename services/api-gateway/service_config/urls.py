from django.urls import path, re_path

from gateway.views import HealthView, ProxyView

urlpatterns = [
    path('health/', HealthView.as_view(), name='gateway-health'),
    re_path(r'^.*$', ProxyView.as_view(), name='gateway-proxy'),
]
