"""
URL configuration for authentication endpoints.
"""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import SignUpView, EmailVerificationView, LoginView, LogoutView

urlpatterns = [
    path('signup/', SignUpView.as_view(), name='signup'),
    path('verify-email/', EmailVerificationView.as_view(), name='verify-email'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
]

