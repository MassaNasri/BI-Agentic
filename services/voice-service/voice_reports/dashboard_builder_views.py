from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .infrastructure.auth_context import extract_identity_context, require_authorized_workspace
from .infrastructure.workspace_client import get_workspace_client
from .models import DashboardPage, ReportPageAssignment, VoiceReport
from .serializers import (
    DashboardPageCreateSerializer,
    DashboardPageReorderSerializer,
    DashboardPageSerializer,
    DashboardPageUpdateSerializer,
    DashboardWidgetBatchUpdateSerializer,
    DashboardWidgetCreateSerializer,
    DashboardWidgetSerializer,
    DashboardWidgetUpdateSerializer,
)
from .services.dashboard_builder_service import (
    attach_widget,
    create_page,
    get_widget_queryset_for_update,
    delete_page,
    delete_widget,
    ensure_workspace_builder_seed,
    list_widgets_queryset,
    reorder_pages,
    update_page,
    update_widget,
)

logger = logging.getLogger(__name__)


def _resolve_workspace_id(request) -> tuple[str, str, str]:
    identity = extract_identity_context(request)
    context = require_authorized_workspace(get_workspace_client().resolve(
        request=request, workspace_hint=identity.workspace_hint, user_id=identity.user_id,
    ))
    return str(context.workspace_id or "").strip(), str(identity.role or "").strip().lower(), str(identity.user_id or "").strip()


def _workspace_response_or_none(workspace_id: str):
    if workspace_id:
        return None
    return Response(
        {"success": False, "error": "User must belong to a workspace"},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _manager_response_or_none(role: str):
    if role == "manager":
        return None
    return Response(
        {"success": False, "error": "Only managers can modify dashboard builder resources."},
        status=status.HTTP_403_FORBIDDEN,
    )


def _serialize_page_with_widgets(page: DashboardPage) -> dict:
    payload = DashboardPageSerializer(page).data
    widgets = (
        list_widgets_queryset(page_ids=[page.id], include_report=True)
        .order_by("order", "id")
    )
    payload["widgets"] = DashboardWidgetSerializer(widgets, many=True).data
    return payload


class DashboardPageListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        workspace_id, _role, _user_id = _resolve_workspace_id(request)
        workspace_error = _workspace_response_or_none(workspace_id)
        if workspace_error is not None:
            return workspace_error

        seed_result = ensure_workspace_builder_seed(
            workspace_id=workspace_id,
            actor_id=_user_id,
            actor_email=str(getattr(request.user, "email", "") or "").strip(),
        )
        logger.info(
            "dashboard_builder_seed workspace=%s page_created=%s widgets_created=%s",
            workspace_id,
            seed_result.get("page_created"),
            seed_result.get("widgets_created"),
        )

        include_widgets = str(request.query_params.get("include_widgets", "true")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        pages = list(
            DashboardPage.objects.filter(workspace_id=workspace_id).order_by("order", "id")
        )
        page_payload = DashboardPageSerializer(pages, many=True).data
        if include_widgets and pages:
            page_ids = [page.id for page in pages]
            widgets = (
                list_widgets_queryset(page_ids=page_ids, include_report=True)
                .order_by("page_id", "order", "id")
            )
            grouped: dict[int, list[dict]] = {page_id: [] for page_id in page_ids}
            for widget in widgets:
                grouped.setdefault(widget.page_id, []).append(DashboardWidgetSerializer(widget).data)
            for page_entry in page_payload:
                page_entry["widgets"] = grouped.get(page_entry["id"], [])

        return Response(
            {
                "success": True,
                "pages": page_payload,
                "count": len(page_payload),
            }
        )

    def post(self, request):
        workspace_id, role, user_id = _resolve_workspace_id(request)
        workspace_error = _workspace_response_or_none(workspace_id)
        if workspace_error is not None:
            return workspace_error
        manager_error = _manager_response_or_none(role)
        if manager_error is not None:
            return manager_error

        serializer = DashboardPageCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        name = str(serializer.validated_data["name"]).strip()
        if not name:
            return Response(
                {"success": False, "error": "name is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if DashboardPage.objects.filter(workspace_id=workspace_id, name__iexact=name).exists():
            return Response(
                {"success": False, "error": "A page with this name already exists in the workspace."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            page = create_page(
                workspace_id=workspace_id,
                name=name,
                description=str(serializer.validated_data.get("description", "") or "").strip(),
                created_by_id=user_id,
                created_by_email=str(getattr(request.user, "email", "") or "").strip(),
                requested_order=serializer.validated_data.get("order"),
            )
        except IntegrityError:
            return Response(
                {"success": False, "error": "Could not create page due to a uniqueness conflict."},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {
                "success": True,
                "page": DashboardPageSerializer(page).data,
            },
            status=status.HTTP_201_CREATED,
        )


class DashboardPageDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, page_id: int):
        workspace_id, _role, _user_id = _resolve_workspace_id(request)
        workspace_error = _workspace_response_or_none(workspace_id)
        if workspace_error is not None:
            return workspace_error

        page = get_object_or_404(DashboardPage, id=page_id, workspace_id=workspace_id)
        return Response(
            {
                "success": True,
                "page": _serialize_page_with_widgets(page),
            }
        )

    def patch(self, request, page_id: int):
        workspace_id, role, _user_id = _resolve_workspace_id(request)
        workspace_error = _workspace_response_or_none(workspace_id)
        if workspace_error is not None:
            return workspace_error
        manager_error = _manager_response_or_none(role)
        if manager_error is not None:
            return manager_error

        page = get_object_or_404(DashboardPage, id=page_id, workspace_id=workspace_id)
        serializer = DashboardPageUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        next_name = serializer.validated_data.get("name")
        if next_name is not None:
            next_name = str(next_name).strip()
            if not next_name:
                return Response(
                    {"success": False, "error": "name cannot be empty"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            duplicate_exists = DashboardPage.objects.filter(
                workspace_id=workspace_id,
                name__iexact=next_name,
            ).exclude(id=page.id).exists()
            if duplicate_exists:
                return Response(
                    {"success": False, "error": "A page with this name already exists in the workspace."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        try:
            page = update_page(
                page=page,
                name=next_name,
                description=serializer.validated_data.get("description"),
                requested_order=serializer.validated_data.get("order"),
            )
        except IntegrityError:
            return Response(
                {"success": False, "error": "Could not update page due to a uniqueness conflict."},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {
                "success": True,
                "page": _serialize_page_with_widgets(page),
            }
        )

    def delete(self, request, page_id: int):
        workspace_id, role, _user_id = _resolve_workspace_id(request)
        workspace_error = _workspace_response_or_none(workspace_id)
        if workspace_error is not None:
            return workspace_error
        manager_error = _manager_response_or_none(role)
        if manager_error is not None:
            return manager_error

        page = get_object_or_404(DashboardPage, id=page_id, workspace_id=workspace_id)
        delete_page(page=page)
        return Response({"success": True, "message": "Page deleted successfully."})


class DashboardPageReorderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        workspace_id, role, _user_id = _resolve_workspace_id(request)
        workspace_error = _workspace_response_or_none(workspace_id)
        if workspace_error is not None:
            return workspace_error
        manager_error = _manager_response_or_none(role)
        if manager_error is not None:
            return manager_error

        serializer = DashboardPageReorderSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        try:
            reordered = reorder_pages(
                workspace_id=workspace_id,
                page_ids=serializer.validated_data["page_ids"],
            )
        except ValueError as exc:
            return Response(
                {"success": False, "error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "success": True,
                "pages": DashboardPageSerializer(reordered, many=True).data,
            }
        )


class DashboardPageWidgetListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, page_id: int):
        workspace_id, _role, _user_id = _resolve_workspace_id(request)
        workspace_error = _workspace_response_or_none(workspace_id)
        if workspace_error is not None:
            return workspace_error

        page = get_object_or_404(DashboardPage, id=page_id, workspace_id=workspace_id)
        widgets = (
            list_widgets_queryset(page_ids=[page.id], include_report=True)
            .order_by("order", "id")
        )
        return Response(
            {
                "success": True,
                "page": DashboardPageSerializer(page).data,
                "widgets": DashboardWidgetSerializer(widgets, many=True).data,
                "count": widgets.count(),
            }
        )

    def post(self, request, page_id: int):
        workspace_id, role, user_id = _resolve_workspace_id(request)
        workspace_error = _workspace_response_or_none(workspace_id)
        if workspace_error is not None:
            return workspace_error
        manager_error = _manager_response_or_none(role)
        if manager_error is not None:
            return manager_error

        page = get_object_or_404(DashboardPage, id=page_id, workspace_id=workspace_id)
        serializer = DashboardWidgetCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        report_id = serializer.validated_data["report_id"]
        report = get_object_or_404(VoiceReport, id=report_id, workspace_id=workspace_id)

        result = attach_widget(
            page=page,
            report=report,
            added_by_id=user_id,
            added_by_email=str(getattr(request.user, "email", "") or "").strip(),
            widget_type=serializer.validated_data["widget_type"],
            requested_order=serializer.validated_data.get("order"),
            x=serializer.validated_data.get("x", 0),
            y=serializer.validated_data.get("y", 0),
            width=serializer.validated_data.get("width", 6),
            height=serializer.validated_data.get("height", 4),
            layout_metadata=serializer.validated_data.get("layout_metadata", {}),
            widget_config=serializer.validated_data.get("widget_config", {}),
        )

        return Response(
            {
                "success": True,
                "widget": DashboardWidgetSerializer(result.widget).data,
                "created": result.created,
            },
            status=status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )


class DashboardWidgetDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, widget_id: int):
        workspace_id, role, user_id = _resolve_workspace_id(request)
        workspace_error = _workspace_response_or_none(workspace_id)
        if workspace_error is not None:
            return workspace_error
        manager_error = _manager_response_or_none(role)
        if manager_error is not None:
            return manager_error

        widget = get_object_or_404(
            get_widget_queryset_for_update(),
            id=widget_id,
            page__workspace_id=workspace_id,
        )

        serializer = DashboardWidgetUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        target_page = None
        target_page_id = serializer.validated_data.get("page_id")
        if target_page_id is not None:
            target_page = get_object_or_404(DashboardPage, id=target_page_id, workspace_id=workspace_id)

        widget = update_widget(
            widget=widget,
            target_page=target_page,
            requested_order=serializer.validated_data.get("order"),
            widget_type=serializer.validated_data.get("widget_type"),
            x=serializer.validated_data.get("x"),
            y=serializer.validated_data.get("y"),
            width=serializer.validated_data.get("width"),
            height=serializer.validated_data.get("height"),
            layout_metadata=serializer.validated_data.get("layout_metadata"),
            widget_config=serializer.validated_data.get("widget_config"),
        )

        return Response({"success": True, "widget": DashboardWidgetSerializer(widget).data})

    def delete(self, request, widget_id: int):
        workspace_id, role, user_id = _resolve_workspace_id(request)
        workspace_error = _workspace_response_or_none(workspace_id)
        if workspace_error is not None:
            return workspace_error
        manager_error = _manager_response_or_none(role)
        if manager_error is not None:
            return manager_error

        widget = get_object_or_404(
            get_widget_queryset_for_update(),
            id=widget_id,
            page__workspace_id=workspace_id,
        )

        delete_widget(widget=widget)
        return Response({"success": True, "message": "Widget removed from page."})


class DashboardWidgetBatchUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        workspace_id, role, user_id = _resolve_workspace_id(request)
        workspace_error = _workspace_response_or_none(workspace_id)
        if workspace_error is not None:
            return workspace_error
        manager_error = _manager_response_or_none(role)
        if manager_error is not None:
            return manager_error

        serializer = DashboardWidgetBatchUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        prepared_updates: list[tuple[dict, ReportPageAssignment, DashboardPage | None]] = []
        for update in serializer.validated_data["updates"]:
            widget = get_object_or_404(
                get_widget_queryset_for_update(),
                id=update["widget_id"],
                page__workspace_id=workspace_id,
            )

            target_page = None
            target_page_id = update.get("page_id")
            if target_page_id is not None:
                target_page = get_object_or_404(DashboardPage, id=target_page_id, workspace_id=workspace_id)
            prepared_updates.append((update, widget, target_page))

        updated_widgets = []
        with transaction.atomic():
            for update, widget, target_page in prepared_updates:
                updated_widget = update_widget(
                    widget=widget,
                    target_page=target_page,
                    requested_order=update.get("order"),
                    widget_type=update.get("widget_type"),
                    x=update.get("x"),
                    y=update.get("y"),
                    width=update.get("width"),
                    height=update.get("height"),
                    layout_metadata=update.get("layout_metadata"),
                    widget_config=update.get("widget_config"),
                )
                updated_widgets.append(updated_widget)

        return Response(
            {
                "success": True,
                "widgets": DashboardWidgetSerializer(updated_widgets, many=True).data,
                "count": len(updated_widgets),
            }
        )
