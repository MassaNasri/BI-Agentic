from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from workspace.views import AdminWorkspaceDetailView, AdminWorkspaceListView

urlpatterns = [
    path('admin/workspaces/', AdminWorkspaceListView.as_view(), name='admin-workspaces'),
    path(
        'admin/workspaces/<int:workspace_id>/',
        AdminWorkspaceDetailView.as_view(),
        name='admin-workspace-detail',
    ),
    path('admin/', admin.site.urls),
    path('workspace/', include('workspace.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
