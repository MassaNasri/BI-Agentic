from django.urls import path
from .views import RunDetectorView, HealthView, MetricsView
from shared.utils.health import ReadyView

urlpatterns = [
    path("run-detector/", RunDetectorView.as_view(), name="run-detector"),
    path("health/", HealthView.as_view()),
    path("ready/", ReadyView.as_view()),
    path("metrics/", MetricsView.as_view()),
]
