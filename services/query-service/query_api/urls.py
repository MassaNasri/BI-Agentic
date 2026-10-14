from django.urls import path

from .views import (
    QueryDefinitionCreateView,
    QueryDefinitionVisualizationView,
    QueryCancelInternalView,
    QueryExecuteInternalView,
    QueryValidateInternalView,
    QueryHealthView,
)

urlpatterns = [
    path('health/', QueryHealthView.as_view(), name='query-health'),
    path('validate/', QueryValidateInternalView.as_view(), name='query-validate'),
    path('execute/', QueryExecuteInternalView.as_view(), name='query-execute'),
    path('cancel/', QueryCancelInternalView.as_view(), name='query-cancel'),
    path('definitions/', QueryDefinitionCreateView.as_view(), name='query-definition-create'),
    path(
        'definitions/<uuid:definition_id>/visualization/',
        QueryDefinitionVisualizationView.as_view(),
        name='query-definition-visualization',
    ),
]
