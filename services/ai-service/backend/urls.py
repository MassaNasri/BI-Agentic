"""
URL configuration for backend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from bi_platform_shared.http.health import liveness_view, readiness_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", liveness_view),
    path("ready/", readiness_view),
    path('api/', include('whisper_app.urls')),
    path('api/reasoning/', include('reasoning_app.urls')),
    path('api/llm/', include('llm_app.urls')),
]

