from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from users.views import AdminUserDetailView, AdminUsersView

urlpatterns = [
    path('admin/users/', AdminUsersView.as_view(), name='admin-users'),
    path('admin/users/<int:user_id>/', AdminUserDetailView.as_view(), name='admin-user-detail'),
    path('admin/', admin.site.urls),
    path('auth/', include('users.auth_urls')),
    path('user/', include('users.user_urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
