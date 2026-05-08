from __future__ import annotations

import logging
import secrets
import uuid
from typing import Any

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .internal_authentication import ServiceInternalTokenAuthentication
from .models import Invitation, Workspace, WorkspaceMember
from .notification_client import get_notification_client
from .permissions import IsAdmin
from .serializers import (
    InternalAttachUserSerializer,
    InternalCreateWorkspaceSerializer,
    InternalInvitationResolveSerializer,
    InternalUserActivationSerializer,
    InvitationRequestSerializer,
    MemberStatusSerializer,
    RoleAssignmentSerializer,
    WorkspaceSerializer,
    WorkspaceUpdateSerializer,
)
from .services.auth_client import AuthServiceError, get_auth_service_client

logger = logging.getLogger(__name__)


<<<<<<< HEAD
=======
def _principal_attr(user: object, *names: str) -> str:
    for name in names:
        value = getattr(user, name, None)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _principal_int(user: object, *names: str) -> int | None:
    raw = _principal_attr(user, *names)
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _principal_role(user: object) -> str:
    return _principal_attr(user, "role").lower()


def _principal_verified(user: object) -> bool:
    return bool(getattr(user, "is_verified", True))


def _principal_active(user: object) -> bool:
    return bool(getattr(user, "is_active", True))


def _principal_name(user: object) -> str:
    return _principal_attr(user, "name")


def _principal_email(user: object) -> str:
    return _principal_attr(user, "email")


def _generate_invitation_token() -> str:
    return f"{uuid.uuid4().hex}{secrets.token_urlsafe(16)}"


def _workspace_base_fields() -> tuple[str, ...]:
    # Use explicit values() reads to avoid hard dependency on optional columns
    # that may not exist yet in transitional shared-DB environments.
    return (
        "id",
        "name",
        "description",
        "company_number",
        "company_address",
        "owner",
        "created_at",
    )


def _get_workspace_row_by_id(workspace_id: int | str | None) -> dict[str, Any] | None:
    if workspace_id in (None, ""):
        return None
    return Workspace.objects.filter(id=int(workspace_id)).values(*_workspace_base_fields()).first()


def _get_owned_workspace_row(user_id: int | None) -> dict[str, Any] | None:
    if user_id is None:
        return None
    return Workspace.objects.filter(owner=user_id).values(*_workspace_base_fields()).first()


def _get_owned_workspace(user_id: int | None) -> Workspace | None:
    if user_id is None:
        return None
    return Workspace.objects.filter(owner=user_id).first()


def _is_workspace_accessible_by_user(*, workspace: Workspace, user_id: int | None, role: str) -> bool:
    if role == "admin":
        return True
    if user_id is None:
        return False
    if role == "manager" and workspace.owner_id == user_id:
        return True
    return WorkspaceMember.objects.filter(
        workspace=workspace,
        user=user_id,
        status="active",
    ).exists()


def _resolve_user_by_email(email: str) -> dict[str, Any] | None:
    try:
        return get_auth_service_client().get_user_by_email(email)
    except AuthServiceError as exc:
        logger.warning("auth_lookup_email_failed email=%s error=%s", email, exc)
        return None


def _resolve_user_by_id(user_id: int) -> dict[str, Any] | None:
    try:
        return get_auth_service_client().get_user_by_id(user_id)
    except AuthServiceError as exc:
        logger.warning("auth_lookup_user_failed user_id=%s error=%s", user_id, exc)
        return None


def _patch_user(user_id: int, updates: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return get_auth_service_client().patch_user(user_id, updates)
    except AuthServiceError as exc:
        logger.warning("auth_patch_user_failed user_id=%s updates=%s error=%s", user_id, updates, exc)
        return None


def _workspace_member_payload(member: WorkspaceMember) -> dict[str, Any]:
    base_status = member.status
    if base_status == "active" and not member.is_user_active:
        base_status = "suspended"
    if base_status == "active" and not member.is_user_verified:
        base_status = "pending_acceptance"
    return {
        "id": member.user_id,
        "name": member.user_name or "",
        "email": member.user_email or member.invited_email or "",
        "role": member.role,
        "status": base_status,
    }


def _resolve_owner_payload(
    *,
    owner_id: int | None,
    fallback_name: str = "",
    fallback_email: str = "",
) -> dict[str, Any]:
    resolved: dict[str, Any] | None = None
    if owner_id is not None:
        resolved = _resolve_user_by_id(owner_id)
    return {
        "id": owner_id,
        "name": str((resolved or {}).get("name") or fallback_name or ""),
        "email": str((resolved or {}).get("email") or fallback_email or ""),
    }


def _workspace_payload_from_row(workspace_row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    owner_raw = workspace_row.get("owner")
    owner_id = int(owner_raw) if owner_raw is not None else None
    owner = _resolve_owner_payload(owner_id=owner_id)
    workspace_payload = {
        "id": workspace_row.get("id"),
        "name": workspace_row.get("name"),
        "description": workspace_row.get("description"),
        "company_number": workspace_row.get("company_number"),
        "company_address": workspace_row.get("company_address"),
        "created_at": workspace_row.get("created_at"),
        "owner_id": owner_id,
        "owner_name": owner["name"],
        "owner_email": owner["email"],
    }
    return workspace_payload, owner


def _owner_payload(workspace: Workspace) -> dict[str, Any]:
    return {
        "id": workspace.owner_id,
        "name": workspace.owner_name,
        "email": workspace.owner_email,
    }


def _build_workspace_members_response(workspace: Workspace) -> dict[str, Any]:
    accepted_members: list[dict[str, Any]] = [
        {
            "id": workspace.owner_id,
            "name": workspace.owner_name,
            "email": workspace.owner_email,
            "role": "manager",
            "status": "active",
        }
    ]
    pending_members: list[dict[str, Any]] = []
    invited_members: list[dict[str, Any]] = []

    for member in WorkspaceMember.objects.filter(workspace=workspace).order_by("id"):
        payload = _workspace_member_payload(member)
        if member.status == "pending_registration":
            invited_members.append(payload)
        elif member.status == "pending_acceptance":
            pending_members.append(payload)
        else:
            accepted_members.append(payload)

    return {
        "workspace_id": workspace.id,
        "workspace_name": workspace.name,
        "accepted_members": accepted_members,
        "pending_members": pending_members,
        "invited_members": invited_members,
        "members": accepted_members,
    }


def _build_workspace_members_response_from_row(workspace_row: dict[str, Any]) -> dict[str, Any]:
    workspace_id = int(workspace_row["id"])
    owner_id = int(workspace_row["owner"])
    owner_payload = _resolve_owner_payload(owner_id=owner_id)

    accepted_members: list[dict[str, Any]] = [
        {
            "id": owner_payload["id"],
            "name": owner_payload["name"],
            "email": owner_payload["email"],
            "role": "manager",
            "status": "active",
        }
    ]
    pending_members: list[dict[str, Any]] = []
    invited_members: list[dict[str, Any]] = []

    user_cache: dict[int, dict[str, Any] | None] = {}
    member_rows = (
        WorkspaceMember.objects.filter(workspace_id=workspace_id)
        .values("id", "user", "invited_email", "role", "status")
        .order_by("id")
    )
    for member in member_rows:
        raw_user_id = member.get("user")
        member_user_id: int | None = None
        if raw_user_id is not None:
            try:
                member_user_id = int(raw_user_id)
            except (TypeError, ValueError):
                member_user_id = None

        if member_user_id is not None and member_user_id == owner_id:
            continue

        user_payload: dict[str, Any] | None = None
        if member_user_id is not None:
            if member_user_id not in user_cache:
                user_cache[member_user_id] = _resolve_user_by_id(member_user_id)
            user_payload = user_cache[member_user_id] or {}

        role_value = str(member.get("role") or "analyst")
        member_status = str(member.get("status") or "active")
        name_value = str((user_payload or {}).get("name") or "")
        email_value = str((user_payload or {}).get("email") or member.get("invited_email") or "")
        is_user_active = bool((user_payload or {}).get("is_active", True))
        is_user_verified = bool((user_payload or {}).get("is_verified", member_status != "pending_acceptance"))

        effective_status = member_status
        if effective_status == "active" and not is_user_active:
            effective_status = "suspended"
        if effective_status == "active" and not is_user_verified:
            effective_status = "pending_acceptance"

        payload = {
            "id": member_user_id,
            "name": name_value,
            "email": email_value,
            "role": role_value,
            "status": effective_status,
        }
        if member_status == "pending_registration":
            invited_members.append(payload)
        elif member_status == "pending_acceptance":
            pending_members.append(payload)
        else:
            accepted_members.append(payload)

    return {
        "workspace_id": workspace_id,
        "workspace_name": workspace_row.get("name"),
        "accepted_members": accepted_members,
        "pending_members": pending_members,
        "invited_members": invited_members,
        "members": accepted_members,
    }


class WorkspaceDetailByIdView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, workspace_id):
        if not _principal_verified(request.user):
            return Response(
                {"success": False, "message": "Please verify your email before accessing workspace features."},
                status=status.HTTP_403_FORBIDDEN,
            )

        workspace_row = _get_workspace_row_by_id(workspace_id)
        if not workspace_row:
            return Response({"success": False, "message": "Workspace not found."}, status=status.HTTP_404_NOT_FOUND)

        user_id = _principal_int(request.user, "id", "pk")
        role = _principal_role(request.user)
        owner_raw = workspace_row.get("owner")
        owner_id = int(owner_raw) if owner_raw is not None else None
        has_access = role == "admin"
        if not has_access and role == "manager" and owner_id is not None and user_id is not None:
            has_access = owner_id == user_id
        if not has_access and user_id is not None:
            has_access = WorkspaceMember.objects.filter(
                workspace_id=int(workspace_row["id"]),
                user=user_id,
                status="active",
            ).exists()
        if not has_access:
            return Response(
                {"success": False, "message": "You do not have access to this workspace."},
                status=status.HTTP_403_FORBIDDEN,
            )

        workspace_payload, owner_payload = _workspace_payload_from_row(workspace_row)
        return Response(
            {
                "success": True,
                "id": workspace_payload["id"],
                "manager_id": owner_payload["id"],
                "workspace": workspace_payload,
                "owner": owner_payload,
            },
            status=status.HTTP_200_OK,
        )


>>>>>>> c791036 (final update)
class WorkspaceUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _principal_verified(request.user):
            return Response(
                {"success": False, "message": "Please verify your email before accessing workspace features."},
                status=status.HTTP_403_FORBIDDEN,
            )

        workspace_row = _get_owned_workspace_row(_principal_int(request.user, "id", "pk"))
        if not workspace_row:
            return Response(
                {"success": False, "message": "Workspace not found. Only managers can access workspace information."},
                status=status.HTTP_404_NOT_FOUND,
            )

        workspace_payload, _ = _workspace_payload_from_row(workspace_row)
        return Response({"success": True, "workspace": workspace_payload}, status=status.HTTP_200_OK)

    def put(self, request):
        if not _principal_verified(request.user):
            return Response(
                {"success": False, "message": "Please verify your email before accessing workspace features."},
                status=status.HTTP_403_FORBIDDEN,
            )

        workspace_row = _get_owned_workspace_row(_principal_int(request.user, "id", "pk"))
        if not workspace_row:
            return Response(
                {"success": False, "message": "Workspace not found. Only managers can update workspace information."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = WorkspaceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updates: dict[str, Any] = {}
        for field in ("name", "description", "company_number", "company_address"):
            if field in serializer.validated_data:
                updates[field] = serializer.validated_data[field]
        if updates:
            Workspace.objects.filter(id=int(workspace_row["id"])).update(**updates)
        refreshed_row = _get_workspace_row_by_id(workspace_row["id"]) or workspace_row
        workspace_payload, _ = _workspace_payload_from_row(refreshed_row)
        return Response(
            {"success": True, "message": "Workspace updated successfully.", "workspace": workspace_payload},
            status=status.HTTP_200_OK,
        )


class WorkspaceMembersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _principal_verified(request.user):
            return Response(
                {"success": False, "message": "Please verify your email before accessing workspace features."},
                status=status.HTTP_403_FORBIDDEN,
            )

        user_id = _principal_int(request.user, "id", "pk")
        role = _principal_role(request.user)
        workspace_row: dict[str, Any] | None = None
        if role == "manager":
            workspace_row = _get_owned_workspace_row(user_id)
        if workspace_row is None and user_id is not None:
            membership = WorkspaceMember.objects.filter(user=user_id, status="active").values("workspace_id").first()
            if membership and membership.get("workspace_id") is not None:
                workspace_row = _get_workspace_row_by_id(membership["workspace_id"])
        if workspace_row is None:
            return Response(
                {"success": False, "message": "You are not a member of any workspace."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response(_build_workspace_members_response_from_row(workspace_row), status=status.HTTP_200_OK)


class InvitationView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        if not _principal_verified(request.user):
            return Response(
                {"success": False, "message": "Please verify your email before accessing workspace features."},
                status=status.HTTP_403_FORBIDDEN,
            )

        owner_id = _principal_int(request.user, "id", "pk")
        workspace = _get_owned_workspace(owner_id)
        if not workspace:
            return Response(
                {"success": False, "message": "Only workspace owners can send invitations."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = InvitationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invited_email = serializer.validated_data["email"].strip().lower()
        invited_role = serializer.validated_data["role"]

        if WorkspaceMember.objects.filter(workspace=workspace, invited_email=invited_email, status="active").exists():
            return Response(
                {"success": False, "message": "This user is already an active member of your workspace."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        Invitation.objects.filter(
            invited_email=invited_email,
            workspace=workspace,
            status__in=["pending", "accepted"],
        ).update(status="expired")
        WorkspaceMember.objects.filter(
            workspace=workspace,
            invited_email=invited_email,
            status__in=["pending_registration", "pending_acceptance"],
        ).delete()

        existing_user = _resolve_user_by_email(invited_email)
        token = _generate_invitation_token()
        invitation = Invitation.objects.create(
            invited_email=invited_email,
            workspace=workspace,
            role=invited_role,
            token=token,
            status="pending",
        )

        if existing_user:
            WorkspaceMember.objects.create(
                workspace=workspace,
                user=int(existing_user.get("id")),
                user_email=str(existing_user.get("email") or invited_email),
                user_name=str(existing_user.get("name") or ""),
                user_role=str(existing_user.get("role") or invited_role),
                is_user_active=bool(existing_user.get("is_active", True)),
                is_user_verified=bool(existing_user.get("is_verified", False)),
                invited_email=invited_email,
                role=invited_role,
                status="pending_acceptance",
            )
        else:
            WorkspaceMember.objects.create(
                workspace=workspace,
                user=None,
                user_email=invited_email,
                user_name="",
                user_role=invited_role,
                is_user_active=True,
                is_user_verified=False,
                invited_email=invited_email,
                role=invited_role,
                status="pending_registration",
            )

        notification_client = get_notification_client()
        notification_result = notification_client.send_event(
            event_type="workspace_invitation",
            event_key=f"workspace-invite:{workspace.id}:{invited_email}",
            payload={
                "invited_email": invited_email,
                "inviter_name": _principal_name(request.user),
                "workspace_name": workspace.name,
                "workspace_id": workspace.id,
                "role": invited_role,
                "token": token,
            },
        )
        if not notification_result.get("success"):
            logger.warning(
                "workspace_invitation_notification_failed workspace=%s email=%s error=%s",
                workspace.id,
                invited_email,
                notification_result.get("error"),
            )

        return Response(
            {
                "success": True,
                "message": "Invitation sent successfully.",
                "invitation": {
                    "email": invited_email,
                    "role": invited_role,
                    "workspace_id": workspace.id,
                    "invitation_id": invitation.id,
                    "expires_at": invitation.expires_at,
                },
            },
            status=status.HTTP_200_OK,
        )


class RoleAssignmentView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def put(self, request, id):
        if not _principal_verified(request.user):
            return Response(
                {"success": False, "message": "Please verify your email before accessing workspace features."},
                status=status.HTTP_403_FORBIDDEN,
            )

        owner_id = _principal_int(request.user, "id", "pk")
        workspace = _get_owned_workspace(owner_id)
        if not workspace:
            return Response({"success": False, "message": "Only workspace owners can assign roles."}, status=status.HTTP_403_FORBIDDEN)

        body = RoleAssignmentSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        new_role = body.validated_data["role"]

        if owner_id is not None and int(id) == int(owner_id):
            return Response({"success": False, "message": "You cannot change your own role."}, status=status.HTTP_403_FORBIDDEN)

        user = _resolve_user_by_id(int(id))
        if not user:
            return Response({"success": False, "message": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        if str(user.get("role") or "").lower() == "manager" and new_role != "manager":
            return Response({"success": False, "message": "You cannot demote another manager."}, status=status.HTTP_403_FORBIDDEN)

        membership = WorkspaceMember.objects.filter(workspace=workspace, user=int(id)).first()
        if not membership and workspace.owner_id != int(id):
            return Response({"success": False, "message": "This user is not a member of your workspace."}, status=status.HTTP_404_NOT_FOUND)

        patched = _patch_user(int(id), {"role": new_role})
        if patched is None:
            return Response({"success": False, "message": "Failed to update role in auth-service."}, status=status.HTTP_502_BAD_GATEWAY)

        if membership:
            membership.role = new_role
            membership.user_role = new_role
            membership.save(update_fields=["role", "user_role"])

        return Response(
            {
                "success": True,
                "message": "Role updated successfully.",
                "member": {
                    "id": int(id),
                    "email": str(patched.get("email") or ""),
                    "name": str(patched.get("name") or ""),
                    "role": str(patched.get("role") or new_role),
                },
            },
            status=status.HTTP_200_OK,
        )


class MemberManageView(APIView):
    permission_classes = [IsAuthenticated]

    def _resolve_workspace(self, request) -> Workspace | None:
        return _get_owned_workspace(_principal_int(request.user, "id", "pk"))

    def get(self, request, id):
        if not _principal_verified(request.user):
            return Response(
                {"success": False, "message": "Please verify your email before accessing workspace features."},
                status=status.HTTP_403_FORBIDDEN,
            )
        workspace = self._resolve_workspace(request)
        if not workspace:
            return Response({"success": False, "message": "Only workspace owners can view member details."}, status=status.HTTP_403_FORBIDDEN)

        if workspace.owner_id == int(id):
            owner = _resolve_user_by_id(int(id)) or {}
            payload = {
                "id": int(id),
                "name": str(owner.get("name") or workspace.owner_name),
                "email": str(owner.get("email") or workspace.owner_email),
                "role": str(owner.get("role") or "manager"),
                "status": "suspended" if not bool(owner.get("is_active", True)) else "active",
            }
            return Response({"success": True, "member": payload}, status=status.HTTP_200_OK)

        member = WorkspaceMember.objects.filter(workspace=workspace, user=int(id)).first()
        if not member:
            return Response({"success": False, "message": "This user is not a member of your workspace."}, status=status.HTTP_404_NOT_FOUND)

        return Response({"success": True, "member": _workspace_member_payload(member)}, status=status.HTTP_200_OK)

    @transaction.atomic
    def put(self, request, id):
        if not _principal_verified(request.user):
            return Response(
                {"success": False, "message": "Please verify your email before accessing workspace features."},
                status=status.HTTP_403_FORBIDDEN,
            )
        workspace = self._resolve_workspace(request)
        if not workspace:
            return Response({"success": False, "message": "Only workspace owners can update members."}, status=status.HTTP_403_FORBIDDEN)

        serializer = MemberStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data["status"]

        member = WorkspaceMember.objects.filter(workspace=workspace, user=int(id)).first()
        if not member:
            return Response({"success": False, "message": "This user is not a member of your workspace."}, status=status.HTTP_404_NOT_FOUND)

        update_fields = []
        if new_status == "active":
            patched = _patch_user(int(id), {"is_active": True})
            if patched:
                member.is_user_active = bool(patched.get("is_active", True))
                member.is_user_verified = bool(patched.get("is_verified", member.is_user_verified))
                update_fields.extend(["is_user_active", "is_user_verified"])
            member.status = "active"
            update_fields.append("status")
        else:
            member.status = "pending_acceptance"
            update_fields.append("status")
        member.save(update_fields=update_fields)

        return Response({"success": True, "message": "Member updated successfully.", "member": _workspace_member_payload(member)})

    @transaction.atomic
    def delete(self, request, id):
        if not _principal_verified(request.user):
            return Response(
                {"success": False, "message": "Please verify your email before accessing workspace features."},
                status=status.HTTP_403_FORBIDDEN,
            )
        owner_id = _principal_int(request.user, "id", "pk")
        workspace = _get_owned_workspace(owner_id)
        if not workspace:
            return Response({"success": False, "message": "Only workspace owners can remove members."}, status=status.HTTP_403_FORBIDDEN)
        if owner_id is not None and int(id) == int(owner_id):
            return Response({"success": False, "message": "You cannot remove yourself from the workspace."}, status=status.HTTP_403_FORBIDDEN)

        member = WorkspaceMember.objects.filter(workspace=workspace, user=int(id)).first()
        if not member:
            return Response({"success": False, "message": "This user is not a member of your workspace."}, status=status.HTTP_404_NOT_FOUND)

        Invitation.objects.filter(workspace=workspace, invited_email=(member.invited_email or member.user_email), status="pending").update(status="expired")
        member.delete()

        return Response({"success": True, "message": "Member removed from workspace successfully."}, status=status.HTTP_200_OK)


class MemberSuspendView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def put(self, request, id):
        if not _principal_verified(request.user):
            return Response(
                {"success": False, "message": "Please verify your email before accessing workspace features."},
                status=status.HTTP_403_FORBIDDEN,
            )
        owner_id = _principal_int(request.user, "id", "pk")
        workspace = _get_owned_workspace(owner_id)
        if not workspace:
            return Response({"success": False, "message": "Only workspace owners can suspend members."}, status=status.HTTP_403_FORBIDDEN)
        if owner_id is not None and int(id) == int(owner_id):
            return Response({"success": False, "message": "You cannot suspend yourself."}, status=status.HTTP_403_FORBIDDEN)

        member = WorkspaceMember.objects.filter(workspace=workspace, user=int(id)).first()
        if not member:
            return Response({"success": False, "message": "This user is not a member of your workspace."}, status=status.HTTP_404_NOT_FOUND)
        if member.role == "manager":
            return Response({"success": False, "message": "You cannot suspend another manager."}, status=status.HTTP_403_FORBIDDEN)

        patched = _patch_user(int(id), {"is_active": False})
        member.is_user_active = bool(patched.get("is_active", False)) if patched else False
        member.status = "suspended"
        member.save(update_fields=["is_user_active", "status"])

        return Response({"success": True, "message": "Member suspended successfully."}, status=status.HTTP_200_OK)


class MemberUnsuspendView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def put(self, request, id):
        if not _principal_verified(request.user):
            return Response(
                {"success": False, "message": "Please verify your email before accessing workspace features."},
                status=status.HTTP_403_FORBIDDEN,
            )
        workspace = _get_owned_workspace(_principal_int(request.user, "id", "pk"))
        if not workspace:
            return Response({"success": False, "message": "Only workspace owners can unsuspend members."}, status=status.HTTP_403_FORBIDDEN)

        member = WorkspaceMember.objects.filter(workspace=workspace, user=int(id)).first()
        if not member:
            return Response({"success": False, "message": "This user is not a member of your workspace."}, status=status.HTTP_404_NOT_FOUND)

        patched = _patch_user(int(id), {"is_active": True})
        member.is_user_active = bool(patched.get("is_active", True)) if patched else True
        member.status = "active"
        member.save(update_fields=["is_user_active", "status"])
        return Response({"success": True, "message": "Member unsuspended successfully."}, status=status.HTTP_200_OK)


class RemovePendingInvitationView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def delete(self, request, email):
        if not _principal_verified(request.user):
            return Response(
                {"success": False, "message": "Please verify your email before accessing workspace features."},
                status=status.HTTP_403_FORBIDDEN,
            )
        workspace = _get_owned_workspace(_principal_int(request.user, "id", "pk"))
        if not workspace:
            return Response({"success": False, "message": "Only workspace owners can remove invitations."}, status=status.HTTP_403_FORBIDDEN)

        email_lower = str(email or "").strip().lower()
        members_deleted = WorkspaceMember.objects.filter(
            workspace=workspace,
            invited_email=email_lower,
            status__in=["pending_registration", "pending_acceptance"],
        ).delete()[0]
        invitations_expired = Invitation.objects.filter(
            workspace=workspace,
            invited_email=email_lower,
            status="pending",
        ).update(status="expired")
        if members_deleted == 0 and invitations_expired == 0:
            return Response({"success": False, "message": "No pending invitation found for this email."}, status=status.HTTP_404_NOT_FOUND)
        return Response({"success": True, "message": "Invitation removed successfully."}, status=status.HTTP_200_OK)


class AcceptInvitationView(APIView):
    permission_classes = []

    @transaction.atomic
    def get(self, request):
        token = str(request.query_params.get("token") or "").strip()
        if not token:
            return Response({"success": False, "message": "Invitation token is required."}, status=status.HTTP_400_BAD_REQUEST)

        invitation = Invitation.objects.select_related("workspace").filter(token=token).first()
        if not invitation:
            return Response({"success": False, "message": "Invalid invitation link."}, status=status.HTTP_400_BAD_REQUEST)
        if invitation.status == "accepted":
            return Response({"success": False, "message": "This invitation has already been used."}, status=status.HTTP_400_BAD_REQUEST)
        if invitation.status == "expired" or invitation.is_expired():
            invitation.status = "expired"
            invitation.save(update_fields=["status"])
            return Response({"success": False, "message": "Invitation link has expired."}, status=status.HTTP_400_BAD_REQUEST)

        workspace = invitation.workspace
        invited_email = invitation.invited_email
        invited_role = invitation.role
        user = _resolve_user_by_email(invited_email)
        if not user:
            return Response(
                {
                    "success": True,
                    "need_register": True,
                    "email": invited_email,
                    "role": invited_role,
                    "invitation_token": token,
                    "message": "Please create an account to accept this invitation.",
                    "workspace": {"id": workspace.id, "name": workspace.name},
                },
                status=status.HTTP_200_OK,
            )

        user_id = int(user.get("id"))
        WorkspaceMember.objects.update_or_create(
            workspace=workspace,
            user=user_id,
            defaults={
                "invited_email": invited_email,
                "user_email": str(user.get("email") or invited_email),
                "user_name": str(user.get("name") or ""),
                "user_role": str(user.get("role") or invited_role),
                "is_user_active": bool(user.get("is_active", True)),
                "is_user_verified": bool(user.get("is_verified", False)),
                "role": invited_role,
                "status": "active",
                "joined_at": timezone.now(),
            },
        )
        invitation.status = "accepted"
        invitation.save(update_fields=["status"])

        if str(user.get("role") or "").lower() != invited_role:
            _patch_user(user_id, {"role": invited_role})

        notification_client = get_notification_client()
        notification_result = notification_client.send_event(
            event_type="workspace_member_joined",
            event_key=f"workspace-join:{workspace.id}:{user_id}",
            payload={
                "workspace_id": workspace.id,
                "workspace_name": workspace.name,
                "owner_email": workspace.owner_email,
                "owner_name": workspace.owner_name,
                "recipient_emails": [workspace.owner_email] if workspace.owner_email else [],
                "joined_user_id": user_id,
                "joined_user_name": str(user.get("name") or ""),
                "joined_user_email": str(user.get("email") or invited_email),
                "joined_role": invited_role,
            },
        )
        if not notification_result.get("success"):
            logger.warning(
                "workspace_member_joined_notification_failed workspace=%s user=%s error=%s",
                workspace.id,
                user_id,
                notification_result.get("error"),
            )

        return Response(
            {
                "success": True,
                "need_login": True,
                "email": invited_email,
                "message": "Invitation accepted! Please log in to access the workspace.",
                "workspace": {"id": workspace.id, "name": workspace.name},
            },
            status=status.HTTP_200_OK,
        )


class AdminWorkspaceListView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        payload = []
        for workspace in Workspace.objects.all().order_by("-created_at"):
            payload.append(
                {
                    "id": workspace.id,
                    "name": workspace.name,
                    "description": workspace.description,
                    "company_number": workspace.company_number,
                    "company_address": workspace.company_address,
                    "created_at": workspace.created_at,
                    "owner": _owner_payload(workspace),
                    "active_members_count": WorkspaceMember.objects.filter(workspace=workspace, status="active").count(),
                    "pending_members_count": WorkspaceMember.objects.filter(
                        workspace=workspace,
                        status__in=["pending_registration", "pending_acceptance"],
                    ).count(),
                }
            )
        return Response({"success": True, "count": len(payload), "workspaces": payload}, status=status.HTTP_200_OK)


class AdminWorkspaceDetailView(APIView):
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request, workspace_id):
        workspace = Workspace.objects.filter(id=workspace_id).first()
        if not workspace:
            return Response({"success": False, "message": "Workspace not found."}, status=status.HTTP_404_NOT_FOUND)

        members_payload = [_workspace_member_payload(member) for member in WorkspaceMember.objects.filter(workspace=workspace)]
        return Response(
            {
                "success": True,
                "workspace": {
                    "id": workspace.id,
                    "name": workspace.name,
                    "description": workspace.description,
                    "company_number": workspace.company_number,
                    "company_address": workspace.company_address,
                    "created_at": workspace.created_at,
                    "owner": _owner_payload(workspace),
                    "members": members_payload,
                },
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, workspace_id):
        workspace = Workspace.objects.filter(id=workspace_id).first()
        if not workspace:
            return Response({"success": False, "message": "Workspace not found."}, status=status.HTTP_404_NOT_FOUND)
        workspace.delete()
        return Response({"success": True, "message": "Workspace deleted successfully."}, status=status.HTTP_200_OK)


class InternalInvitationResolveView(APIView):
    authentication_classes = [ServiceInternalTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = InternalInvitationResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["token"]

        invitation = Invitation.objects.select_related("workspace").filter(token=token).first()
        if not invitation:
            return Response({"success": False, "message": "Invalid invitation link."}, status=status.HTTP_404_NOT_FOUND)
        if invitation.status == "accepted":
            return Response({"success": False, "message": "This invitation has already been used."}, status=status.HTTP_409_CONFLICT)
        if invitation.status == "expired" or invitation.is_expired():
            invitation.status = "expired"
            invitation.save(update_fields=["status"])
            return Response({"success": False, "message": "Invitation link has expired."}, status=status.HTTP_410_GONE)

        return Response(
            {
                "success": True,
                "invitation": {
                    "token": invitation.token,
                    "invited_email": invitation.invited_email,
                    "role": invitation.role,
                    "workspace_id": invitation.workspace_id,
                    "workspace_name": invitation.workspace.name,
                    "status": invitation.status,
                },
            },
            status=status.HTTP_200_OK,
        )


class InternalAttachUserToInvitationView(APIView):
    authentication_classes = [ServiceInternalTokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        serializer = InternalAttachUserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        invitation = Invitation.objects.select_related("workspace").filter(token=payload["token"]).first()
        if not invitation:
            return Response({"success": False, "message": "Invalid invitation link."}, status=status.HTTP_404_NOT_FOUND)
        if invitation.status == "expired" or invitation.is_expired():
            invitation.status = "expired"
            invitation.save(update_fields=["status"])
            return Response({"success": False, "message": "Invitation link has expired."}, status=status.HTTP_410_GONE)

        workspace = invitation.workspace
        member_status = "active" if payload["is_verified"] and payload["is_active"] else "pending_acceptance"
        joined_at = timezone.now() if member_status == "active" else None

        member, _ = WorkspaceMember.objects.update_or_create(
            workspace=workspace,
            invited_email=invitation.invited_email,
            defaults={
                "user": payload["user_id"],
                "user_email": payload["user_email"],
                "user_name": payload.get("user_name") or "",
                "user_role": payload["user_role"],
                "is_user_active": payload["is_active"],
                "is_user_verified": payload["is_verified"],
                "role": invitation.role,
                "status": member_status,
                "joined_at": joined_at,
            },
        )

        invitation.status = "accepted"
        invitation.save(update_fields=["status"])

        return Response(
            {
                "success": True,
                "workspace_id": workspace.id,
                "workspace_name": workspace.name,
                "member_status": member.status,
                "member_id": member.id,
            },
            status=status.HTTP_200_OK,
        )


class InternalCreateManagerWorkspaceView(APIView):
    authentication_classes = [ServiceInternalTokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        serializer = InternalCreateWorkspaceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        workspace_row = _get_owned_workspace_row(payload["user_id"])
        if workspace_row is None:
            default_name = f"{(payload.get('user_name') or 'Manager').strip()}'s Workspace"
            workspace = Workspace.objects.create(
                name=(payload.get("workspace_name") or default_name).strip(),
                owner=payload["user_id"],
            )
            workspace_row = _get_workspace_row_by_id(workspace.id) or {
                "id": workspace.id,
                "name": workspace.name,
                "description": workspace.description,
                "company_number": workspace.company_number,
                "company_address": workspace.company_address,
                "owner": workspace.owner,
                "created_at": workspace.created_at,
            }

        workspace_payload, owner_payload = _workspace_payload_from_row(workspace_row)
        owner_name = owner_payload["name"] or str(payload.get("user_name") or "")
        owner_email = owner_payload["email"] or str(payload.get("user_email") or "")
        workspace_payload["owner_name"] = owner_name
        workspace_payload["owner_email"] = owner_email
        return Response(
            {"success": True, "workspace": workspace_payload},
            status=status.HTTP_200_OK,
        )


class InternalUserWorkspacesView(APIView):
    authentication_classes = [ServiceInternalTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        role = str(request.query_params.get("role") or "").strip().lower()
        if role == "manager":
            workspace = _get_owned_workspace_row(int(user_id))
            data = None
            if workspace:
                data = {
                    "id": workspace["id"],
                    "name": workspace["name"],
                    "manager_id": int(workspace["owner"]),
                }
            return Response({"success": True, "workspace": data}, status=status.HTTP_200_OK)

        workspace_ids = list(
            WorkspaceMember.objects.filter(user=int(user_id), status="active").values_list("workspace_id", flat=True)
        )
        id_set = {int(wid) for wid in workspace_ids if wid is not None}
        workspace_rows = Workspace.objects.filter(id__in=id_set).values("id", "name", "owner")
        workspace_map = {int(row["id"]): row for row in workspace_rows}
        data = []
        for wid in workspace_ids:
            if wid is None:
                continue
            row = workspace_map.get(int(wid))
            if not row:
                continue
            data.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "manager_id": int(row["owner"]),
                }
            )
        return Response({"success": True, "workspace": data}, status=status.HTTP_200_OK)


class InternalActivateUserMembershipsView(APIView):
    authentication_classes = [ServiceInternalTokenAuthentication]
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        serializer = InternalUserActivationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        user_id = payload["user_id"]
        user_email = payload["user_email"].lower()
        user_name = payload.get("user_name") or ""
        user_role = payload["user_role"]
        is_active = payload["is_active"]
        is_verified = payload["is_verified"]

        members = WorkspaceMember.objects.filter(user=user_id).select_related("workspace")
        if not members.exists():
            members = WorkspaceMember.objects.filter(invited_email=user_email).select_related("workspace")

        activation_results: list[dict[str, Any]] = []
        notifications: list[dict[str, Any]] = []
        now = timezone.now()

        for member in members:
            member.user = user_id
            member.user_email = user_email
            member.user_name = user_name
            member.user_role = user_role
            member.is_user_active = is_active
            member.is_user_verified = is_verified

            if not is_active:
                member.status = "suspended"
            elif is_verified and member.status in {"pending_acceptance", "pending_registration"}:
                member.status = "active"
                if member.joined_at is None:
                    member.joined_at = now
            member.save()

            activation_results.append(
                {
                    "workspace_id": member.workspace_id,
                    "workspace_name": member.workspace.name,
                    "status": member.status,
                    "role": member.role,
                }
            )
            if member.status == "active":
                notifications.append(
                    {
                        "workspace_id": member.workspace_id,
                        "workspace_name": member.workspace.name,
                        "owner_email": member.workspace.owner_email,
                        "owner_name": member.workspace.owner_name,
                        "joined_user_id": user_id,
                        "joined_user_name": user_name,
                        "joined_user_email": user_email,
                        "joined_role": member.role,
                    }
                )

        return Response(
            {
                "success": True,
                "memberships": activation_results,
                "notifications": notifications,
            },
            status=status.HTTP_200_OK,
        )
