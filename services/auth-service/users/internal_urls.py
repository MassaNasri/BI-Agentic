"""Internal service URLs for auth-service."""

from django.urls import path

from .views import InternalUserByEmailView, InternalUserDetailView

urlpatterns = [
    path('users/by-email/', InternalUserByEmailView.as_view(), name='internal-user-by-email'),
    path('users/<int:user_id>/', InternalUserDetailView.as_view(), name='internal-user-detail'),
]

