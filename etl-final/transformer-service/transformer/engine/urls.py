from django.urls import path
from .views import TestTransformView, QuarantineReviewView, QuarantineReprocessView, HealthView, MetricsView

urlpatterns = [
    path("test/", TestTransformView.as_view()),
    path("quarantine/", QuarantineReviewView.as_view()),
    path("quarantine/reprocess/", QuarantineReprocessView.as_view()),
    path("health/", HealthView.as_view()),
    path("metrics/", MetricsView.as_view()),
]
