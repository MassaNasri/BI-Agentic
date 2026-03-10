from django.urls import path
from .views import (
    ConnectionLogsView,
    SchemaLogsView,
    ExtractLogsView,
    TransformLogsView,
    LoadLogsView,
    LineageQueryView,
    QualityTrendsView,
    HealthView,
    MetricsView,
)

urlpatterns = [
    path("logs/connections/", ConnectionLogsView.as_view()),
    path("logs/schema/", SchemaLogsView.as_view()),
    path("logs/extract/", ExtractLogsView.as_view()),
    path("logs/transform/", TransformLogsView.as_view()),
    path("logs/load/", LoadLogsView.as_view()),
    path("lineage/<str:row_id>/", LineageQueryView.as_view()),
    path("quality/trends/", QualityTrendsView.as_view()),
    path("health/", HealthView.as_view()),
    path("metrics/", MetricsView.as_view()),
]
