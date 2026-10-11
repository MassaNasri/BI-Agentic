from django.urls import path
from .views import TestLoaderView
from shared.utils.health import ReadyView
from django.http import JsonResponse


def health_view(request):
    return JsonResponse({"status": "alive", "service": "etl-loader"})

urlpatterns = [
    path("health/", health_view),
    path("ready/", ReadyView.as_view()),
    path("test/", TestLoaderView.as_view()),
]
