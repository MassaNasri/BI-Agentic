from django.urls import path

from . import views

urlpatterns = [
    path('dashboard/', views.WorkspaceDashboardView.as_view(), name='workspace-dashboard'),
    path('dashboard/stats/', views.DashboardStatsView.as_view(), name='dashboard-stats'),
    path('reports/', views.ReportListView.as_view(), name='report-list'),
    path('<int:report_id>/sql/', views.SQLEditView.as_view(), name='sql-edit'),
    path('<int:report_id>/', views.ReportDetailView.as_view(), name='report-detail'),
]
