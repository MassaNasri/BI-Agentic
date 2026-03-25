"""
URL configuration for user profile endpoints.
"""
from django.urls import path
from .views import ChangePasswordView, DeactivateAccountView, ProfileView

urlpatterns = [
    path('profile/', ProfileView.as_view(), name='profile'),
    path('change-password/', ChangePasswordView.as_view(), name='change-password'),
    path('deactivate/', DeactivateAccountView.as_view(), name='deactivate-account'),
]

