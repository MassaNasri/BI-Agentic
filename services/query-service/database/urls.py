from django.urls import path
from .views import (
    DatabaseUploadView,
    DatabaseDetailView,
    DatabasePreviewView,
    DatabaseStatusView,
    DatabaseHealthCheckView
)

urlpatterns = [
    # Health check endpoint
    path('health/', DatabaseHealthCheckView.as_view(), name='database-health'),
    
    # Database management endpoints
    path('upload/', DatabaseUploadView.as_view(), name='database-upload'),
    path('', DatabaseDetailView.as_view(), name='database-detail'),
    path('preview/', DatabasePreviewView.as_view(), name='database-preview'),
    path('<int:database_id>/status/', DatabaseStatusView.as_view(), name='database-status'),
]

