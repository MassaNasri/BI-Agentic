"""
Voice Reports URLs

API endpoints for voice-driven BI system.
"""

from django.urls import path
from . import views
from . import dashboard_builder_views

urlpatterns = [
    # Health check
    path('health/', views.HealthCheckView.as_view(), name='voice-reports-health'),
    
    # Voice upload and processing
    path('upload/', views.VoiceUploadView.as_view(), name='voice-upload'),
    path('text-query/', views.TextQueryView.as_view(), name='text-query'),
    
    # Query execution
    path('<int:report_id>/execute/', views.QueryExecuteView.as_view(), name='query-execute'),
    
    # SQL editing (Analyst only)
    path('<int:report_id>/sql/', views.SQLEditView.as_view(), name='sql-edit'),
    path('<int:report_id>/ai-trace/', views.AITraceDetailView.as_view(), name='report-ai-trace'),
    path('<int:report_id>/chart-types/capabilities/', views.ReportChartTypeCapabilitiesView.as_view(), name='report-chart-type-capabilities'),
    path('<int:report_id>/chart-types/switch/', views.ReportChartTypeSwitchView.as_view(), name='report-chart-type-switch'),
    
    # Report management
    path('reports/', views.ReportListView.as_view(), name='report-list'),
    path('<int:report_id>/', views.ReportDetailView.as_view(), name='report-detail'),
    
    # Workspace dashboard (Executive view)
    path('dashboard/stats/', views.DashboardStatsView.as_view(), name='dashboard-stats'),
    path('dashboard/', views.WorkspaceDashboardView.as_view(), name='workspace-dashboard'),
    path('pages/', dashboard_builder_views.DashboardPageListCreateView.as_view(), name='dashboard-page-list-create'),
    path('pages/reorder/', dashboard_builder_views.DashboardPageReorderView.as_view(), name='dashboard-page-reorder'),
    path('pages/<int:page_id>/', dashboard_builder_views.DashboardPageDetailView.as_view(), name='dashboard-page-detail'),
    path('pages/<int:page_id>/widgets/', dashboard_builder_views.DashboardPageWidgetListCreateView.as_view(), name='dashboard-page-widgets'),
    path('widgets/batch-layout/', dashboard_builder_views.DashboardWidgetBatchUpdateView.as_view(), name='dashboard-widget-batch-update'),
    path('widgets/<int:widget_id>/', dashboard_builder_views.DashboardWidgetDetailView.as_view(), name='dashboard-widget-detail'),
]

