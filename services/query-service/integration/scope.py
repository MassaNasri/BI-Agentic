from rest_framework import status
from rest_framework.response import Response


def principal_attr(user, *names):
    for name in names:
        value = getattr(user, name, None)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def principal_user_id(user):
    try:
        value = int(principal_attr(user, "id", "pk"))
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


def principal_workspace_id(request):
    try:
        value = int(principal_attr(request.user, "workspace_id"))
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


def require_manager_scope(request):
    if principal_attr(request.user, "role").lower() != "manager":
        return None, Response(
            {"success": False, "error": {"code": "PERMISSION_DENIED", "message": "Only managers can manage data sources."}},
            status=status.HTTP_403_FORBIDDEN,
        )
    workspace_id = principal_workspace_id(request)
    if workspace_id is None:
        return None, Response(
            {"success": False, "error": {"code": "WORKSPACE_REQUIRED", "message": "A workspace-scoped token is required."}},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return workspace_id, None
