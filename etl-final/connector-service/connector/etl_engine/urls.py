from django.urls import path
from .views import (
    UploadFileView, ConnectDBView, HealthView, MetricsView,
    DatabaseCapabilitiesView, DatabaseConnectionTestView, DatabaseDiscoveryView,
    DatabaseSnapshotView, SQLitePrepareView,
)
from shared.utils.health import ReadyView

urlpatterns = [
    path("upload/", UploadFileView.as_view()),
    path("connect-db/", ConnectDBView.as_view()),
    path("databases/capabilities/", DatabaseCapabilitiesView.as_view()),
    path("databases/test/", DatabaseConnectionTestView.as_view()),
    path("databases/discover/", DatabaseDiscoveryView.as_view()),
    path("databases/snapshot/", DatabaseSnapshotView.as_view()),
    path("databases/sqlite/prepare/", SQLitePrepareView.as_view()),
    path("health/", HealthView.as_view()),
    path("ready/", ReadyView.as_view()),
    path("metrics/", MetricsView.as_view()),
]
