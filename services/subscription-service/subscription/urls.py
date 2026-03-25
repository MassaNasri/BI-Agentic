from django.urls import path

from .views import (
    AdminPlanDetailView,
    AdminPlanListCreateView,
    AdminStatsView,
    CheckAccessView,
    CurrentSubscriptionView,
    HealthView,
    PlanCatalogView,
    SubscribeView,
)

urlpatterns = [
    path('check-access/', CheckAccessView.as_view(), name='subscription-check-access-legacy'),
    path('subscribe/', SubscribeView.as_view(), name='subscription-subscribe-legacy'),
    path('plans/', PlanCatalogView.as_view(), name='subscription-plan-catalog-legacy'),
    path('subscription/health/', HealthView.as_view(), name='subscription-health'),
    path('subscription/plans/', PlanCatalogView.as_view(), name='subscription-plan-catalog'),
    path('subscription/subscribe/', SubscribeView.as_view(), name='subscription-subscribe'),
    path('subscription/current/', CurrentSubscriptionView.as_view(), name='subscription-current'),
    path('subscription/check-access/', CheckAccessView.as_view(), name='subscription-check-access'),
    path('admin/plans/', AdminPlanListCreateView.as_view(), name='admin-plan-list-create'),
    path('admin/plans/<int:plan_id>/', AdminPlanDetailView.as_view(), name='admin-plan-detail'),
    path('admin/stats/', AdminStatsView.as_view(), name='admin-stats'),
]
