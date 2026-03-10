from django.urls import path
from .views import UploadFileView, ConnectDBView, HealthView, MetricsView

urlpatterns = [
    path("upload/", UploadFileView.as_view()),
    path("connect-db/", ConnectDBView.as_view()),
    path("health/", HealthView.as_view()),
    path("metrics/", MetricsView.as_view()),
]
