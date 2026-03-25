"""
URL configuration for authentication endpoints.
"""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    EmailVerificationView,
    ForgotPasswordRequestView,
    ForgotPasswordResetView,
    ForgotPasswordVerifyView,
    LoginView,
    LogoutView,
    SignUpView,
)

urlpatterns = [
    path('signup/', SignUpView.as_view(), name='signup'),
    path('verify-email/', EmailVerificationView.as_view(), name='verify-email'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('forgot-password/request/', ForgotPasswordRequestView.as_view(), name='forgot-password-request'),
    path('forgot-password/verify/', ForgotPasswordVerifyView.as_view(), name='forgot-password-verify'),
    path('forgot-password/reset/', ForgotPasswordResetView.as_view(), name='forgot-password-reset'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
]

