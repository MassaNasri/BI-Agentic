"""
URL configuration for user profile endpoints.
"""
from django.urls import path
from .views import ProfileView, DeactivateAccountView

urlpatterns = [
    path('profile/', ProfileView.as_view(), name='profile'),
    path('deactivate/', DeactivateAccountView.as_view(), name='deactivate-account'),
]

