from django.urls import path
from .views import RunExtractorView, ExtractionProgressView, HealthView, MetricsView

urlpatterns = [
    path("run/", RunExtractorView.as_view()),
    path("progress/<str:extraction_id>/", ExtractionProgressView.as_view()),
    path("progress/", ExtractionProgressView.as_view()),
    path("health/", HealthView.as_view()),
    path("metrics/", MetricsView.as_view()),
]
