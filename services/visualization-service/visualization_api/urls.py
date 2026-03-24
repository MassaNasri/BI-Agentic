from django.urls import path

from .views import (
    VisualizationHealthView,
    CreateQuestionView,
    CreateDashboardView,
    AddQuestionToDashboardView,
    QuestionEmbedUrlView,
    DashboardEmbedUrlView,
)

urlpatterns = [
    path('health/', VisualizationHealthView.as_view(), name='visualization-health'),
    path('question/create/', CreateQuestionView.as_view(), name='create-question'),
    path('dashboard/create/', CreateDashboardView.as_view(), name='create-dashboard'),
    path('dashboard/add-question/', AddQuestionToDashboardView.as_view(), name='add-question-to-dashboard'),
    path('question/<int:question_id>/embed-url/', QuestionEmbedUrlView.as_view(), name='question-embed-url'),
    path('dashboard/<int:dashboard_id>/embed-url/', DashboardEmbedUrlView.as_view(), name='dashboard-embed-url'),
]
