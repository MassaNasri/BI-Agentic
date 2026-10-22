from django.urls import path
from .views import (
    DatabaseUploadView,
    DatabaseDetailView,
    DatabasePreviewView,
    DatabaseSchemaView,
    DatasetListView,
    DatabaseHealthCheckView
    , DatabaseSourceCapabilitiesView, DatabaseSourceTestView,
    DatabaseSourceDiscoveryView, DatabaseSnapshotStartView, SQLiteSourcePrepareView
)
from integration.views import SourcesView, SourceDetailView, SourceCredentialView, SourceReplacementView, SourceReplacementActionView

urlpatterns = [
    # Health check endpoint
    path('health/', DatabaseHealthCheckView.as_view(), name='database-health'),
    
    # Database management endpoints
    path('upload/', DatabaseUploadView.as_view(), name='database-upload'),
    path('datasets/', DatasetListView.as_view(), name='dataset-list'),
    path('', DatabaseDetailView.as_view(), name='database-detail'),
    path('preview/', DatabasePreviewView.as_view(), name='database-preview'),
    path('schema/', DatabaseSchemaView.as_view(), name='database-schema'),
    path('sources/capabilities/', DatabaseSourceCapabilitiesView.as_view(), name='database-source-capabilities'),
    path('sources/', SourcesView.as_view(), name='data-sources'),
    path('sources/<uuid:source_id>/', SourceDetailView.as_view(), name='data-source-detail'),
    path('sources/<uuid:source_id>/credential/<str:action>/', SourceCredentialView.as_view(), name='data-source-credential'),
    path('sources/<uuid:source_id>/replacement/', SourceReplacementView.as_view(), name='data-source-replacement'),
    path('sources/<uuid:source_id>/replacement/<str:action>/', SourceReplacementActionView.as_view(), name='data-source-replacement-action'),
    path('sources/test/', DatabaseSourceTestView.as_view(), name='database-source-test'),
    path('sources/discover/', DatabaseSourceDiscoveryView.as_view(), name='database-source-discover'),
    path('sources/snapshot/', DatabaseSnapshotStartView.as_view(), name='database-source-snapshot'),
    path('sources/sqlite/prepare/', SQLiteSourcePrepareView.as_view(), name='database-source-sqlite-prepare'),
]

