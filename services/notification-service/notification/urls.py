from django.urls import path

from .views import (
    NotificationEventView,
    NotificationHealthView,
    SubscriptionExpiryWarningRunView,
)

urlpatterns = [
    path('notification/health/', NotificationHealthView.as_view(), name='notification-health'),
    path('notification/events/', NotificationEventView.as_view(), name='notification-events'),
    path(
        'notification/subscriptions/expiry-warnings/run/',
        SubscriptionExpiryWarningRunView.as_view(),
        name='notification-subscription-expiry-warnings-run',
    ),
]
