"""
Compatibility URL module for legacy imports.

`service_config.urls` historically included `voice_reports.voice_urls`.
Keep this file as a thin alias to the canonical `voice_reports.urls`
to avoid route drift between duplicate URL modules.
"""

from .urls import urlpatterns  # noqa: F401
