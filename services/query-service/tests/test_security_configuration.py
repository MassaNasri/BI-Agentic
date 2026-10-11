from __future__ import annotations

import os
from pathlib import Path


def _resolve_repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in (current.parent, *current.parents):
        if (candidate / "bi_platform_shared").is_dir():
            return candidate
    raise RuntimeError("Could not locate repository root containing bi_platform_shared")


REPO_ROOT = _resolve_repo_root()


def test_active_django_settings_do_not_enable_debug_or_open_cors_by_default():
    if (REPO_ROOT / "services").is_dir():
        settings_files = [
            REPO_ROOT / "services/api-gateway/service_config/settings.py",
            REPO_ROOT / "services/auth-service/service_config/settings.py",
            REPO_ROOT / "services/workspace-service/service_config/settings.py",
            REPO_ROOT / "services/report-service/service_config/settings.py",
            REPO_ROOT / "services/voice-service/service_config/settings.py",
            REPO_ROOT / "services/query-service/service_config/settings.py",
            REPO_ROOT / "services/visualization-service/service_config/settings.py",
            REPO_ROOT / "services/subscription-service/service_config/settings.py",
            REPO_ROOT / "services/notification-service/service_config/settings.py",
        ]
    else:
        # The Query image intentionally packages only its own service and the
        # shared library. Test the active packaged settings in that layout.
        settings_files = [REPO_ROOT / "service_config/settings.py"]

    for path in settings_files:
        assert path.is_file(), path
        text = path.read_text(encoding="utf-8")
        assert "CORS_ALLOW_ALL_ORIGINS = True" not in text, path
        assert "DEBUG = os.getenv('DEBUG', 'True')" not in text, path
        assert "ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '*')" not in text, path


def test_active_runtime_config_does_not_contain_removed_sample_credentials():
    candidate_paths = [
        REPO_ROOT / "docker-compose.yml",
        REPO_ROOT / ".env",
        REPO_ROOT / ".env.example",
    ]
    checked_paths = [path for path in candidate_paths if path.is_file()]
    forbidden_tokens = [
        "StrongPassword123",
        "etl_pass123",
        "user_etl",
        "CLICKHOUSE_USER: etl_user",
        "SURREAL_USER: root",
        "SURREAL_PASS: root",
        "WHISPER_MODEL_NAME=tiny",
        "WHISPER_TASK=translate",
    ]

    for path in checked_paths:
        text = path.read_text(encoding="utf-8")
        for token in forbidden_tokens:
            assert token not in text, (path, token)

    if not checked_paths:
        # Root config is not copied into service images. Validate the active
        # container environment without logging any values.
        runtime_config = "\n".join(str(value) for value in os.environ.values())
        for token in forbidden_tokens:
            assert token not in runtime_config, ("container_environment", token)


def test_all_django_services_require_an_explicit_profile_and_reject_production_placeholders():
    if not (REPO_ROOT / "services").is_dir():
        return
    settings_files = list((REPO_ROOT / "services").glob("*/service_config/settings.py"))
    settings_files.append(REPO_ROOT / "services/ai-service/backend/settings.py")
    assert settings_files
    for path in settings_files:
        text = path.read_text(encoding="utf-8")
        assert "APP_ENV not in" in text, path
        assert "Production DJANGO_SECRET_KEY is a placeholder" in text, path
