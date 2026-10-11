from django.urls import path
from .views import (
    DatabaseUploadView,
    DatabaseDetailView,
    DatabasePreviewView,
    DatabaseSchemaView,
    DatabaseHealthCheckView
    , DatabaseSourceCapabilitiesView, DatabaseSourceTestView,
    DatabaseSourceDiscoveryView, DatabaseSnapshotStartView, SQLiteSourcePrepareView
)

urlpatterns = [
    # Health check endpoint
    path('health/', DatabaseHealthCheckView.as_view(), name='database-health'),
    
    # Database management endpoints
    path('upload/', DatabaseUploadView.as_view(), name='database-upload'),
    path('', DatabaseDetailView.as_view(), name='database-detail'),
    path('preview/', DatabasePreviewView.as_view(), name='database-preview'),
    path('schema/', DatabaseSchemaView.as_view(), name='database-schema'),
    path('sources/capabilities/', DatabaseSourceCapabilitiesView.as_view(), name='database-source-capabilities'),
    path('sources/test/', DatabaseSourceTestView.as_view(), name='database-source-test'),
    path('sources/discover/', DatabaseSourceDiscoveryView.as_view(), name='database-source-discover'),
    path('sources/snapshot/', DatabaseSnapshotStartView.as_view(), name='database-source-snapshot'),
    path('sources/sqlite/prepare/', SQLiteSourcePrepareView.as_view(), name='database-source-sqlite-prepare'),
]

