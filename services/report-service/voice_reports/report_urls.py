from django.urls import path

from . import views

urlpatterns = [
    path('health/', views.HealthCheckView.as_view(), name='voice-reports-health'),
    path('dashboard/', views.WorkspaceDashboardView.as_view(), name='workspace-dashboard'),
    path('dashboard/stats/', views.DashboardStatsView.as_view(), name='dashboard-stats'),
    path('reports/', views.ReportListView.as_view(), name='report-list'),
    path('pages/', views.DashboardPageListCreateView.as_view(), name='dashboard-page-list-create'),
    path('pages/reorder/', views.DashboardPageReorderView.as_view(), name='dashboard-page-reorder'),
    path('pages/<int:page_id>/', views.DashboardPageDetailView.as_view(), name='dashboard-page-detail'),
    path('pages/<int:page_id>/widgets/', views.DashboardPageWidgetListCreateView.as_view(), name='dashboard-page-widgets'),
    path('widgets/batch-layout/', views.DashboardWidgetBatchUpdateView.as_view(), name='dashboard-widget-batch-update'),
    path('widgets/<int:widget_id>/', views.DashboardWidgetDetailView.as_view(), name='dashboard-widget-detail'),
    path('<int:report_id>/sql/', views.SQLEditView.as_view(), name='sql-edit'),
    path('<int:report_id>/ai-trace/', views.AITraceDetailView.as_view(), name='report-ai-trace'),
    path('<int:report_id>/chart-types/capabilities/', views.ReportChartTypeCapabilitiesView.as_view(), name='report-chart-type-capabilities'),
    path('<int:report_id>/chart-types/switch/', views.ReportChartTypeSwitchView.as_view(), name='report-chart-type-switch'),
    path('<int:report_id>/', views.ReportDetailView.as_view(), name='report-detail'),
]
