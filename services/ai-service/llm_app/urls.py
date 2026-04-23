from django.urls import path
from .views import forecast_dataset_view, forecast_detect_view, intent_test_view

urlpatterns = [
    path("intent/", intent_test_view, name="intent_test"),
    path("forecasting/detect/", forecast_detect_view, name="forecast_detect"),
    path("forecasting/dataset/", forecast_dataset_view, name="forecast_dataset"),
]

