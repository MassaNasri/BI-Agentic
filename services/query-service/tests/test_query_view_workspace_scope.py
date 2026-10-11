from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _resolve_repo_root() -> Path:
    current = Path(__file__).resolve()
    for candidate in (current.parent, *current.parents):
        if (candidate / "bi_platform_shared").is_dir():
            return candidate
    raise RuntimeError("Could not locate repository root containing bi_platform_shared")


REPO_ROOT = _resolve_repo_root()
SERVICE_ROOT = REPO_ROOT / "services" / "query-service"
if not SERVICE_ROOT.is_dir():
    SERVICE_ROOT = REPO_ROOT
for path in (REPO_ROOT, SERVICE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_config.settings")

import django

django.setup()

from query_api.views import (  # noqa: E402
    WorkspaceRequestScopeError,
    _authorized_workspace_id,
)


def _request(*, claim=None, requested=None):
    return SimpleNamespace(
        user=SimpleNamespace(workspace_id=claim),
        data={} if requested is None else {"workspace_id": requested},
    )


def test_workspace_claim_is_authoritative():
    assert _authorized_workspace_id(_request(claim="3", requested=3)) == 3


def test_cross_workspace_payload_is_forbidden_before_resolution():
    with pytest.raises(WorkspaceRequestScopeError) as raised:
        _authorized_workspace_id(_request(claim=1, requested=2))

    assert raised.value.code == "workspace_scope_mismatch"
    assert raised.value.http_status == 403


def test_missing_workspace_claim_is_unauthorized():
    with pytest.raises(WorkspaceRequestScopeError) as raised:
        _authorized_workspace_id(_request(claim=None, requested=1))

    assert raised.value.code == "workspace_claim_missing"
    assert raised.value.http_status == 401
