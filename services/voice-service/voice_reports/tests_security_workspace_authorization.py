from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from rest_framework.exceptions import NotFound, PermissionDenied

from voice_reports.infrastructure.auth_context import (
    WorkspaceAuthorizationInvalid,
    WorkspaceDependencyUnavailable,
    require_authorized_workspace,
)
from voice_reports.infrastructure.workspace_client import (
    WorkspaceClient,
    WorkspaceResolutionStatus,
)


def _request():
    return SimpleNamespace(META={"HTTP_AUTHORIZATION": "Bearer test-token"})


@pytest.mark.parametrize(
    ("status_code", "expected_status", "exception"),
    [
        (401, WorkspaceResolutionStatus.DENIED, PermissionDenied),
        (403, WorkspaceResolutionStatus.DENIED, PermissionDenied),
        (404, WorkspaceResolutionStatus.NOT_FOUND, NotFound),
    ],
)
def test_requested_workspace_never_survives_denial(status_code, expected_status, exception):
    client = WorkspaceClient()
    client._get = Mock(return_value=SimpleNamespace(status_code=status_code, content=b"{}", json=lambda: {}))

    resolution = client.resolve(request=_request(), workspace_hint="999999", user_id="1")

    assert resolution.status is expected_status
    assert resolution.workspace_id == ""
    with pytest.raises(exception):
        require_authorized_workspace(resolution)


def test_timeout_fails_closed_as_bounded_dependency_failure():
    client = WorkspaceClient()
    client._get = Mock(side_effect=requests.Timeout("late"))
    resolution = client.resolve(request=_request(), workspace_hint="22", user_id="1")
    assert resolution.status is WorkspaceResolutionStatus.DEPENDENCY_UNAVAILABLE
    assert resolution.workspace_id == ""
    with pytest.raises(WorkspaceDependencyUnavailable) as exc:
        require_authorized_workspace(resolution)
    assert exc.value.status_code == 503


@pytest.mark.parametrize("payload", [{}, {"id": "different"}, {"workspace": []}])
def test_malformed_or_mismatched_workspace_response_fails_closed(payload):
    client = WorkspaceClient()
    client._get = Mock(return_value=SimpleNamespace(status_code=200, content=b"x", json=lambda: payload))
    resolution = client.resolve(request=_request(), workspace_hint="22", user_id="1")
    assert resolution.status is WorkspaceResolutionStatus.INVALID_RESPONSE
    assert resolution.workspace_id == ""
    with pytest.raises(WorkspaceAuthorizationInvalid):
        require_authorized_workspace(resolution)


def test_only_matching_positive_membership_becomes_trusted_context():
    client = WorkspaceClient()
    client._get = Mock(
        return_value=SimpleNamespace(
            status_code=200,
            content=b"x",
            json=lambda: {"workspace": {"id": 22, "owner_id": 7}},
        )
    )
    resolution = client.resolve(request=_request(), workspace_hint="22", user_id="1")
    assert resolution.authorized is True
    assert require_authorized_workspace(resolution).workspace_id == "22"
