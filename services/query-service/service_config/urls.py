from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from database.views import IngestionDatasetStatusView
from bi_platform_shared.http.health import liveness_view, readiness_view

urlpatterns = [
    path('health/', liveness_view, name='health'),
    path('ready/', readiness_view, name='ready'),
    path('admin/', admin.site.urls),
    path('database/', include('database.urls')),
    path('query/', include('query_api.urls')),
    path(
        'internal/v1/ingestion/jobs/<uuid:job_id>/dataset-status',
        IngestionDatasetStatusView.as_view(),
        name='internal-ingestion-dataset-status',
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
