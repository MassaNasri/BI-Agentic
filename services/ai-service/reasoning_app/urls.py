from django.urls import path
from .views import reasoning_test_view

urlpatterns = [
    path("test/", reasoning_test_view, name="reasoning_test"),
]

