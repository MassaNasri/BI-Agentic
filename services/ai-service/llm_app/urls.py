from django.urls import path
from .views import intent_test_view

urlpatterns = [
    path("intent/", intent_test_view, name="intent_test"),
]

