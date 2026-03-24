from django.urls import path

from . import views

urlpatterns = [
    path('health/', views.HealthCheckView.as_view(), name='voice-reports-health'),
    path('upload/', views.VoiceUploadView.as_view(), name='voice-upload'),
    path('<int:report_id>/execute/', views.QueryExecuteView.as_view(), name='query-execute'),
]
