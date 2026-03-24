from django.urls import path

from .views import QueryExecuteInternalView, QueryValidateInternalView, QueryHealthView

urlpatterns = [
    path('health/', QueryHealthView.as_view(), name='query-health'),
    path('validate/', QueryValidateInternalView.as_view(), name='query-validate'),
    path('execute/', QueryExecuteInternalView.as_view(), name='query-execute'),
]
