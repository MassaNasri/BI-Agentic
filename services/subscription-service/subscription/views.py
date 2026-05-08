from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import logging
import os
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

try:  # pragma: no cover
    from bi_platform_shared.http import HttpClientError, get_default_client
except Exception:  # pragma: no cover
    HttpClientError = Exception  # type: ignore[assignment,misc]

    def get_default_client():  # type: ignore[no-redef]
        raise RuntimeError("bi_platform_shared.http unavailable")

from .models import FreeTierUsage, Payment, Plan, Subscription
from .notification_client import get_notification_client
from .serializers import (
    AccessCheckSerializer,
    PaymentSerializer,
    PlanSerializer,
    SubscribeSerializer,
    SubscriptionSerializer,
)

logger = logging.getLogger(__name__)

LIMIT_REACHED_MESSAGE = "You have reached your limit. Please subscribe."
WORKSPACE_SERVICE_URL = os.getenv("WORKSPACE_SERVICE_URL", "http://workspace-service:8002").rstrip("/")
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth-service:8001").rstrip("/")


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


def _auth_headers(request) -> dict[str, str]:
    headers: dict[str, str] = {}
    auth_header = str(request.META.get("HTTP_AUTHORIZATION", "") or "").strip()
    if auth_header:
        headers["Authorization"] = auth_header
    return headers


def _http_get_json(url: str, *, request, timeout: tuple[float, float] = (3.0, 10.0)) -> tuple[int, dict[str, Any]]:
    try:
        response = get_default_client().get(
            url,
            headers=_auth_headers(request),
            timeout=timeout,
            attach_internal_api_key=False,
        )
    except HttpClientError as exc:  # type: ignore[misc]
        logger.warning("subscription_http_get_failed url=%s error=%s", url, exc)
        return 503, {"success": False, "message": "service_unavailable"}
    except Exception as exc:  # pragma: no cover
        logger.warning("subscription_http_get_unexpected url=%s error=%s", url, exc)
        return 503, {"success": False, "message": "service_unavailable"}

    try:
        payload = response.json() if response.content else {}
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return int(response.status_code), payload


def _normalize_workspace_payload(payload: dict[str, Any], workspace_id: int) -> dict[str, Any]:
    workspace_obj = payload.get("workspace") if isinstance(payload.get("workspace"), dict) else {}
    owner = payload.get("owner") if isinstance(payload.get("owner"), dict) else workspace_obj.get("owner")
    if not isinstance(owner, dict):
        owner = {}
    normalized_id = payload.get("id") or workspace_obj.get("id") or workspace_id
    return {
        "id": int(normalized_id),
        "name": workspace_obj.get("name") or payload.get("name") or "",
        "owner": {
            "id": owner.get("id"),
            "name": owner.get("name"),
            "email": owner.get("email"),
        },
        "manager_id": payload.get("manager_id") or owner.get("id"),
    }


def _resolve_workspace_for_access(request, workspace_id: int) -> dict[str, Any] | None:
    role = _principal_role(request.user)
    if role == "admin":
        status_code, payload = _http_get_json(
            f"{WORKSPACE_SERVICE_URL}/admin/workspaces/{workspace_id}/",
            request=request,
        )
        if status_code == 200 and payload.get("success"):
            return _normalize_workspace_payload(payload, workspace_id)
        return None

    status_code, payload = _http_get_json(
        f"{WORKSPACE_SERVICE_URL}/workspace/{workspace_id}/",
        request=request,
    )
    if status_code == 200 and payload.get("success"):
        return _normalize_workspace_payload(payload, workspace_id)
    return None


def _resolve_workspace_for_manager_or_admin(request, workspace_id: int) -> dict[str, Any] | None:
    role = _principal_role(request.user)
    workspace = _resolve_workspace_for_access(request, workspace_id)
    if workspace is None:
        return None

    if role == "admin":
        return workspace

    if role != "manager":
        return None

    user_id = _principal_int(request.user, "id", "pk")
    manager_id = workspace.get("manager_id")
    try:
        manager_id_int = int(manager_id) if manager_id not in (None, "") else None
    except (TypeError, ValueError):
        manager_id_int = None
    if user_id is None or manager_id_int is None or user_id != manager_id_int:
        return None
    return workspace


def _fetch_auth_users_summary(request) -> tuple[dict[str, int], str | None]:
    status_code, payload = _http_get_json(f"{AUTH_SERVICE_URL}/admin/users/", request=request)
    if status_code != 200 or not payload.get("success"):
        return {"total": 0, "active": 0, "admins": 0}, "auth_service_unavailable"

    users = payload.get("users") if isinstance(payload.get("users"), list) else []
    total = int(payload.get("count") or len(users) or 0)
    active = 0
    admins = 0
    for user in users:
        if not isinstance(user, dict):
            continue
        if bool(user.get("is_active")):
            active += 1
        if str(user.get("role") or "").strip().lower() == "admin":
            admins += 1
    return {"total": total, "active": active, "admins": admins}, None


def _fetch_workspace_total(request) -> tuple[int, str | None]:
    status_code, payload = _http_get_json(f"{WORKSPACE_SERVICE_URL}/admin/workspaces/", request=request)
    if status_code != 200 or not payload.get("success"):
        return 0, "workspace_service_unavailable"
    return int(payload.get("count") or 0), None


def _resolve_active_subscription(workspace_id):
    today = timezone.now().date()
    subscription = (
        Subscription.objects.select_related("plan")
        .filter(workspace_id=workspace_id, is_active=True)
        .order_by("-created_at")
        .first()
    )
    if not subscription:
        return None

    if subscription.end_date and subscription.end_date < today:
        subscription.is_active = False
        subscription.save(update_fields=["is_active", "updated_at"])
        return None

    return subscription


def _check_and_optionally_consume(workspace_id, consume):
    free_limit = int(getattr(settings, "FREE_TIER_VOICE_REQUEST_LIMIT", 3))
    today = timezone.now().date()

    with transaction.atomic():
        active_subscription = (
            Subscription.objects.select_for_update()
            .select_related("plan")
            .filter(workspace_id=workspace_id, is_active=True)
            .order_by("-created_at")
            .first()
        )

        if active_subscription and active_subscription.end_date and active_subscription.end_date < today:
            active_subscription.is_active = False
            active_subscription.save(update_fields=["is_active", "updated_at"])
            active_subscription = None

        if active_subscription:
            limit = active_subscription.plan.max_voice_requests
            used = active_subscription.voice_requests_used
            allowed = used < limit

            if allowed and consume:
                active_subscription.voice_requests_used += 1
                active_subscription.save(update_fields=["voice_requests_used", "updated_at"])
                used = active_subscription.voice_requests_used

            remaining = max(0, limit - used)
            return {
                "allowed": allowed,
                "remaining_requests": remaining,
                "limit": limit,
                "used_requests": used,
                "is_subscribed": True,
                "plan": {
                    "id": active_subscription.plan.id,
                    "name": active_subscription.plan.name,
                    "has_mcp_access": active_subscription.plan.has_mcp_access,
                },
            }

        usage, _ = FreeTierUsage.objects.select_for_update().get_or_create(workspace_id=workspace_id)
        used = usage.requests_used
        allowed = used < free_limit

        if allowed and consume:
            usage.requests_used += 1
            usage.save(update_fields=["requests_used", "updated_at"])
            used = usage.requests_used

        remaining = max(0, free_limit - used)
        return {
            "allowed": allowed,
            "remaining_requests": remaining,
            "limit": free_limit,
            "used_requests": used,
            "is_subscribed": False,
            "plan": None,
        }


def _require_admin(request) -> Response | None:
    if _principal_role(request.user) != "admin":
        return Response(
            {"success": False, "message": "Admin role required."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


class HealthView(APIView):
    permission_classes = []

    def get(self, request):
        return Response({"success": True, "service": "subscription-service"}, status=status.HTTP_200_OK)


class PlanCatalogView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        plans = Plan.objects.filter(is_active=True).order_by("price_monthly", "name")
        serializer = PlanSerializer(plans, many=True)
        return Response({"success": True, "plans": serializer.data}, status=status.HTTP_200_OK)


class SubscribeView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = SubscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        workspace_id = serializer.validated_data["workspace_id"]
        payment_method = serializer.validated_data["payment_method"]
        plan = serializer.context["plan"]

        user_role = _principal_role(request.user)
        if user_role not in ["manager", "admin"]:
            return Response(
                {"success": False, "message": "Only managers or admins can activate subscriptions."},
                status=status.HTTP_403_FORBIDDEN,
            )

        workspace = _resolve_workspace_for_manager_or_admin(request, workspace_id)
        if not workspace:
            return Response(
                {"success": False, "message": "Workspace not found or access denied."},
                status=status.HTTP_404_NOT_FOUND,
            )

        user_id = _principal_int(request.user, "id", "pk")
        if user_id is None:
            return Response(
                {"success": False, "message": "Invalid authenticated principal: missing user id."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        with transaction.atomic():
            today = timezone.now().date()
            Subscription.objects.filter(workspace_id=workspace_id, is_active=True).update(
                is_active=False,
                end_date=today,
                updated_at=timezone.now(),
            )

            subscription = Subscription.objects.create(
                workspace_id=workspace_id,
                plan=plan,
                start_date=today,
                end_date=today + timedelta(days=plan.duration_days),
                is_active=True,
                voice_requests_used=0,
                created_by_user_id=user_id,
            )

            payment = Payment.objects.create(
                user_id=user_id,
                workspace_id=workspace_id,
                subscription=subscription,
                amount=plan.price_monthly,
                payment_method=payment_method,
                status=Payment.STATUS_SUCCESS,
            )

        logger.info(
            "Subscription activated workspace=%s plan=%s user=%s payment=%s",
            workspace_id,
            plan.id,
            user_id,
            payment.id,
        )

        owner = workspace.get("owner") if isinstance(workspace, dict) else {}
        if not isinstance(owner, dict):
            owner = {}
        owner_email = owner.get("email")
        owner_name = owner.get("name")
        notification_client = get_notification_client()
        notification_result = notification_client.send_event(
            event_type="subscription_activated",
            event_key=f"subscription-activated:{subscription.id}",
            payload={
                "workspace_id": workspace_id,
                "workspace_name": workspace.get("name") if isinstance(workspace, dict) else None,
                "owner_email": owner_email,
                "owner_name": owner_name,
                "recipient_emails": [owner_email] if owner_email else [],
                "plan_name": plan.name,
                "duration_days": plan.duration_days,
                "start_date": subscription.start_date.isoformat() if subscription.start_date else None,
                "end_date": subscription.end_date.isoformat() if subscription.end_date else None,
                "subscription_id": subscription.id,
            },
        )
        if not notification_result.get("success"):
            logger.warning(
                "subscription_activated notification dispatch failed workspace=%s subscription=%s error=%s",
                workspace_id,
                subscription.id,
                notification_result.get("error"),
            )

        return Response(
            {
                "success": True,
                "message": "Subscription activated successfully.",
                "subscription": SubscriptionSerializer(subscription).data,
                "payment": PaymentSerializer(payment).data,
            },
            status=status.HTTP_201_CREATED,
        )


class CheckAccessView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = AccessCheckSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        workspace_id = serializer.validated_data["workspace_id"]
        consume = serializer.validated_data["consume"]

        workspace = _resolve_workspace_for_access(request, workspace_id)
        if not workspace:
            return Response(
                {"success": False, "message": "Workspace not found or access denied."},
                status=status.HTTP_403_FORBIDDEN,
            )

        access_payload = _check_and_optionally_consume(workspace_id=workspace_id, consume=consume)
        response_payload = {"success": True, **access_payload}
        if not access_payload["allowed"]:
            response_payload["message"] = LIMIT_REACHED_MESSAGE
        return Response(response_payload, status=status.HTTP_200_OK)


class CurrentSubscriptionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = AccessCheckSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        workspace_id = serializer.validated_data["workspace_id"]

        workspace = _resolve_workspace_for_access(request, workspace_id)
        if not workspace:
            return Response(
                {"success": False, "message": "Workspace not found or access denied."},
                status=status.HTTP_403_FORBIDDEN,
            )

        subscription = _resolve_active_subscription(workspace_id=workspace_id)
        if not subscription:
            return Response({"success": True, "subscription": None}, status=status.HTTP_200_OK)

        return Response(
            {"success": True, "subscription": SubscriptionSerializer(subscription).data},
            status=status.HTTP_200_OK,
        )


class AdminPlanListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        denied = _require_admin(request)
        if denied is not None:
            return denied
        plans = Plan.objects.all().order_by("name")
        serializer = PlanSerializer(plans, many=True)
        return Response({"success": True, "plans": serializer.data}, status=status.HTTP_200_OK)

    def post(self, request):
        denied = _require_admin(request)
        if denied is not None:
            return denied
        serializer = PlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = serializer.save()
        return Response({"success": True, "plan": PlanSerializer(plan).data}, status=status.HTTP_201_CREATED)


class AdminPlanDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, plan_id):
        denied = _require_admin(request)
        if denied is not None:
            return denied
        plan = get_object_or_404(Plan, id=plan_id)
        serializer = PlanSerializer(instance=plan, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"success": True, "plan": serializer.data}, status=status.HTTP_200_OK)

    def patch(self, request, plan_id):
        denied = _require_admin(request)
        if denied is not None:
            return denied
        plan = get_object_or_404(Plan, id=plan_id)
        serializer = PlanSerializer(instance=plan, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"success": True, "plan": serializer.data}, status=status.HTTP_200_OK)

    def delete(self, request, plan_id):
        denied = _require_admin(request)
        if denied is not None:
            return denied
        plan = get_object_or_404(Plan, id=plan_id)
        if plan.subscriptions.exists():
            return Response(
                {
                    "success": False,
                    "message": "Plan cannot be deleted because subscriptions already exist. Deactivate it instead.",
                },
                status=status.HTTP_409_CONFLICT,
            )
        plan.delete()
        return Response({"success": True, "message": "Plan deleted successfully."}, status=status.HTTP_200_OK)


class AdminStatsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        denied = _require_admin(request)
        if denied is not None:
            return denied

        successful_payments = Payment.objects.filter(status=Payment.STATUS_SUCCESS)
        revenue = successful_payments.aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))["total"]
        free_tier_usage = FreeTierUsage.objects.aggregate(total=Coalesce(Sum("requests_used"), 0))["total"]
        subscribed_usage = Subscription.objects.aggregate(total=Coalesce(Sum("voice_requests_used"), 0))["total"]

        users_summary, users_error = _fetch_auth_users_summary(request)
        workspace_total, workspace_error = _fetch_workspace_total(request)
        warnings = [warning for warning in [users_error, workspace_error] if warning]

        payload = {
            "success": True,
            "users": {
                "total": int(users_summary["total"]),
                "active": int(users_summary["active"]),
                "admins": int(users_summary["admins"]),
            },
            "workspaces": {
                "total": int(workspace_total),
            },
            "plans": {
                "total": Plan.objects.count(),
                "active": Plan.objects.filter(is_active=True).count(),
            },
            "subscriptions": {
                "total": Subscription.objects.count(),
                "active": Subscription.objects.filter(is_active=True).count(),
            },
            "payments": {
                "count": successful_payments.count(),
                "revenue": str(revenue),
            },
            "voice_usage": {
                "free_tier_requests": int(free_tier_usage or 0),
                "subscribed_requests": int(subscribed_usage or 0),
            },
            "stats_source": {
                "users": "auth-service",
                "workspaces": "workspace-service",
            },
        }
        if warnings:
            payload["warnings"] = warnings
        return Response(payload, status=status.HTTP_200_OK)
