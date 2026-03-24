from django.urls import path
from .views import transcribe_view

urlpatterns = [
    path("transcribe/",transcribe_view, name="transcribe"),
]
