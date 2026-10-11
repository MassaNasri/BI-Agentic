from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.db import connection, transaction
from django.utils import timezone

from voice_reports.models import DashboardPage, ReportPageAssignment, VoiceReport

DEFAULT_WIDGET_WIDTH = 6
DEFAULT_WIDGET_HEIGHT = 4
GRID_COLUMNS = 12
LEGACY_WIDGET_ONLY_FIELDS = (
    "id",
    "page_id",
    "report_id",
    "order",
    "added_at",
    "added_by_id",
    "added_by_email",
)
REQUIRED_WIDGET_COLUMNS = {
    "widget_type",
    "x",
    "y",
    "width",
    "height",
    "layout_metadata",
    "widget_config",
}


def _clamp_insert_index(raw_index: int | None, size: int) -> int:
    if raw_index is None:
        return size
    if raw_index < 0:
        return 0
    if raw_index > size:
        return size
    return raw_index


def _clone_json(value):
    if isinstance(value, dict):
        return dict(value)
    return {}


def dashboard_widget_columns_ready() -> bool:
    table_name = ReportPageAssignment._meta.db_table
    with connection.cursor() as cursor:
        table_description = connection.introspection.get_table_description(cursor, table_name)
    existing_columns = {column.name for column in table_description}
    return REQUIRED_WIDGET_COLUMNS.issubset(existing_columns)


def _locked_workspace_pages(workspace_id: str) -> list[DashboardPage]:
    return list(
        DashboardPage.objects.select_for_update()
        .filter(workspace_id=workspace_id)
        .order_by("order", "id")
    )


def _persist_page_order(pages: list[DashboardPage]) -> None:
    dirty: list[DashboardPage] = []
    for idx, page in enumerate(pages):
        if page.order != idx:
            page.order = idx
            dirty.append(page)
    if dirty:
        DashboardPage.objects.bulk_update(dirty, ["order"])


def _locked_page_widgets(page_id: int) -> list[ReportPageAssignment]:
    queryset = ReportPageAssignment.objects.select_for_update().filter(page_id=page_id)
    if not dashboard_widget_columns_ready():
        queryset = queryset.only(*LEGACY_WIDGET_ONLY_FIELDS)
    return list(queryset.order_by("order", "id"))


def list_widgets_queryset(*, page_ids: list[int] | None = None, include_report: bool = True):
    queryset = ReportPageAssignment.objects
    if include_report:
        queryset = queryset.select_related("report")
    if page_ids is not None:
        queryset = queryset.filter(page_id__in=page_ids)
    if not dashboard_widget_columns_ready():
        fields = list(LEGACY_WIDGET_ONLY_FIELDS)
        if include_report:
            fields.extend(
                [
                    "report__id",
                    "report__title",
                    "report__status",
                    "report__chart_type",
                    "report__metabase_question_id",
                    "report__embed_url",
                ]
            )
        queryset = queryset.only(*fields)
    return queryset


def get_widget_queryset_for_update():
    queryset = ReportPageAssignment.objects.select_related("page", "report")
    if not dashboard_widget_columns_ready():
        queryset = queryset.only(
            "id",
            "page_id",
            "report_id",
            "order",
            "added_at",
            "added_by_id",
            "added_by_email",
            "page__id",
            "page__workspace_id",
            "report__id",
        )
    return queryset


def _persist_widget_order(widgets: list[ReportPageAssignment]) -> None:
    dirty: list[ReportPageAssignment] = []
    for idx, widget in enumerate(widgets):
        if widget.order != idx:
            widget.order = idx
            dirty.append(widget)
    if dirty:
        ReportPageAssignment.objects.bulk_update(dirty, ["order"])


def _legacy_insert_widget_row(
    *,
    page_id: int,
    report_id: int,
    order: int,
    added_by_id: str,
    added_by_email: str,
) -> int:
    table_name = connection.ops.quote_name(ReportPageAssignment._meta.db_table)
    order_column = connection.ops.quote_name("order")
    timestamp = timezone.now()
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute(
                f"""
                INSERT INTO {table_name} (report_id, page_id, {order_column}, added_at, added_by_id, added_by_email)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                [report_id, page_id, order, timestamp, added_by_id, added_by_email],
            )
            row = cursor.fetchone()
            return int(row[0])

        cursor.execute(
            f"""
            INSERT INTO {table_name} (report_id, page_id, {order_column}, added_at, added_by_id, added_by_email)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            [report_id, page_id, order, timestamp, added_by_id, added_by_email],
        )
        return int(cursor.lastrowid)


def _widget_position_for_order(order_index: int) -> tuple[int, int]:
    # Place legacy widgets in a simple 2-column grid on the first page.
    widgets_per_row = max(1, GRID_COLUMNS // DEFAULT_WIDGET_WIDTH)
    column_index = order_index % widgets_per_row
    row_index = order_index // widgets_per_row
    return column_index * DEFAULT_WIDGET_WIDTH, row_index * DEFAULT_WIDGET_HEIGHT


def normalize_page_orders(workspace_id: str) -> None:
    with transaction.atomic():
        pages = _locked_workspace_pages(workspace_id)
        _persist_page_order(pages)


def normalize_widget_orders(page_id: int) -> None:
    with transaction.atomic():
        widgets = _locked_page_widgets(page_id)
        _persist_widget_order(widgets)


@transaction.atomic
def ensure_workspace_builder_seed(
    *,
    workspace_id: str,
    actor_id: str | None = None,
    actor_email: str | None = None,
) -> dict:
    """
    Ensure legacy workspace reports are represented in the builder model.

    - Create a first dashboard page when none exists.
    - Backfill unassigned reports onto the first page as widgets.
    """
    if not workspace_id:
        return {"page_created": False, "widgets_created": 0, "primary_page_id": None}

    resolved_actor_id = str(actor_id or "").strip() or "system"
    resolved_actor_email = str(actor_email or "").strip()

    pages = _locked_workspace_pages(workspace_id)
    _persist_page_order(pages)

    page_created = False
    if not pages:
        first_page = DashboardPage.objects.create(
            workspace_id=workspace_id,
            name="Page 1",
            description="Auto-created during dashboard builder migration.",
            order=0,
            created_by_id=resolved_actor_id,
            created_by_email=resolved_actor_email,
        )
        pages = [first_page]
        page_created = True

    primary_page = pages[0]
    extended_widget_schema = dashboard_widget_columns_ready()
    primary_widgets = _locked_page_widgets(primary_page.id)
    _persist_widget_order(primary_widgets)
    next_order = len(primary_widgets)

    assigned_report_ids = set(
        ReportPageAssignment.objects.select_for_update()
        .filter(page__workspace_id=workspace_id)
        .values_list("report_id", flat=True)
    )

    reports = list(
        VoiceReport.objects.filter(workspace_id=workspace_id)
        .only("id")
        .order_by("created_at", "id")
    )

    pending_widgets: list[ReportPageAssignment] = []
    pending_legacy_rows: list[dict] = []
    for report in reports:
        if report.id in assigned_report_ids:
            continue
        if extended_widget_schema:
            x, y = _widget_position_for_order(next_order)
            pending_widgets.append(
                ReportPageAssignment(
                    page=primary_page,
                    report=report,
                    widget_type="report",
                    order=next_order,
                    x=x,
                    y=y,
                    width=DEFAULT_WIDGET_WIDTH,
                    height=DEFAULT_WIDGET_HEIGHT,
                    layout_metadata={},
                    widget_config={},
                    added_by_id=resolved_actor_id,
                    added_by_email=resolved_actor_email,
                )
            )
        else:
            pending_legacy_rows.append(
                {
                    "page_id": primary_page.id,
                    "report_id": report.id,
                    "order": next_order,
                    "added_by_id": resolved_actor_id,
                    "added_by_email": resolved_actor_email,
                }
            )
        next_order += 1

    if extended_widget_schema and pending_widgets:
        ReportPageAssignment.objects.bulk_create(pending_widgets)
    elif not extended_widget_schema and pending_legacy_rows:
        for row in pending_legacy_rows:
            _legacy_insert_widget_row(**row)

    return {
        "page_created": page_created,
        "widgets_created": len(pending_widgets) + len(pending_legacy_rows),
        "primary_page_id": primary_page.id,
    }


@transaction.atomic
def create_page(
    *,
    workspace_id: str,
    name: str,
    description: str,
    created_by_id: str,
    created_by_email: str,
    requested_order: int | None,
) -> DashboardPage:
    pages = _locked_workspace_pages(workspace_id)
    _persist_page_order(pages)

    insert_at = _clamp_insert_index(requested_order, len(pages))
    dirty: list[DashboardPage] = []
    for idx, row in enumerate(pages):
        next_order = idx if idx < insert_at else idx + 1
        if row.order != next_order:
            row.order = next_order
            dirty.append(row)
    if dirty:
        DashboardPage.objects.bulk_update(dirty, ["order"])

    page = DashboardPage.objects.create(
        workspace_id=workspace_id,
        name=name,
        description=description,
        created_by_id=created_by_id,
        created_by_email=created_by_email,
        order=insert_at,
    )
    return page


@transaction.atomic
def update_page(
    *,
    page: DashboardPage,
    name: str | None = None,
    description: str | None = None,
    requested_order: int | None = None,
) -> DashboardPage:
    if name is not None:
        page.name = name
    if description is not None:
        page.description = description

    workspace_id = page.workspace_id
    pages = _locked_workspace_pages(workspace_id)
    _persist_page_order(pages)

    if requested_order is not None:
        ordered_ids = [p.id for p in pages if p.id != page.id]
        insert_at = _clamp_insert_index(requested_order, len(ordered_ids))
        ordered_ids.insert(insert_at, page.id)
        page_map = {p.id: p for p in pages}
        reordered = [page_map[pid] for pid in ordered_ids if pid in page_map]
        _persist_page_order(reordered)
        page.order = insert_at

    page.save()
    return page


@transaction.atomic
def reorder_pages(*, workspace_id: str, page_ids: Iterable[int]) -> list[DashboardPage]:
    pages = _locked_workspace_pages(workspace_id)
    _persist_page_order(pages)

    page_id_list = list(page_ids)
    existing_ids = [p.id for p in pages]
    if set(page_id_list) != set(existing_ids):
        raise ValueError("page_ids must include each workspace page exactly once.")

    page_map = {p.id: p for p in pages}
    reordered = [page_map[pid] for pid in page_id_list]
    _persist_page_order(reordered)
    return reordered


@transaction.atomic
def delete_page(*, page: DashboardPage) -> None:
    workspace_id = page.workspace_id
    page_id = page.id
    page.delete()

    pages = _locked_workspace_pages(workspace_id)
    pages = [p for p in pages if p.id != page_id]
    _persist_page_order(pages)


@dataclass
class WidgetUpsertResult:
    widget: ReportPageAssignment
    created: bool


@transaction.atomic
def attach_widget(
    *,
    page: DashboardPage,
    report: VoiceReport,
    added_by_id: str,
    added_by_email: str,
    widget_type: str,
    requested_order: int | None,
    x: int,
    y: int,
    width: int,
    height: int,
    layout_metadata: dict,
    widget_config: dict,
) -> WidgetUpsertResult:
    extended_widget_schema = dashboard_widget_columns_ready()
    page_widgets = _locked_page_widgets(page.id)
    _persist_widget_order(page_widgets)

    widget = (
        get_widget_queryset_for_update()
        .select_for_update()
        .filter(page=page, report=report)
        .first()
    )

    created = False
    if widget is None:
        created = True
        if extended_widget_schema:
            widget = ReportPageAssignment(
                page=page,
                report=report,
                added_by_id=added_by_id,
                added_by_email=added_by_email,
            )
        else:
            insert_at = _clamp_insert_index(requested_order, len(page_widgets))
            created_widget_id = _legacy_insert_widget_row(
                page_id=page.id,
                report_id=report.id,
                order=insert_at,
                added_by_id=added_by_id,
                added_by_email=added_by_email,
            )
            widget = get_widget_queryset_for_update().get(id=created_widget_id)
            ids = [w.id for w in page_widgets if w.id]
            ids.insert(insert_at, widget.id)
            reordered = []
            widget_map = {w.id: w for w in _locked_page_widgets(page.id)}
            for idx, widget_id in enumerate(ids):
                row = widget_map.get(widget_id)
                if row is None:
                    continue
                if row.order != idx:
                    row.order = idx
                    reordered.append(row)
            if reordered:
                ReportPageAssignment.objects.bulk_update(reordered, ["order"])
            return WidgetUpsertResult(widget=widget, created=created)

    if extended_widget_schema:
        widget.widget_type = widget_type
        widget.x = x
        widget.y = y
        widget.width = width
        widget.height = height
        widget.layout_metadata = _clone_json(layout_metadata)
        widget.widget_config = _clone_json(widget_config)

    ids = [w.id for w in page_widgets if w.id and w.id != widget.id]
    if requested_order is None and not created:
        insert_at = _clamp_insert_index(int(widget.order or 0), len(ids))
    else:
        insert_at = _clamp_insert_index(requested_order, len(ids))
    widget.order = insert_at
    widget.save()

    ids.insert(insert_at, widget.id)
    reordered = []
    widget_map = {w.id: w for w in _locked_page_widgets(page.id)}
    for idx, widget_id in enumerate(ids):
        row = widget_map.get(widget_id)
        if row is None:
            continue
        if row.order != idx:
            row.order = idx
            reordered.append(row)
    if reordered:
        ReportPageAssignment.objects.bulk_update(reordered, ["order"])

    return WidgetUpsertResult(widget=widget, created=created)


@transaction.atomic
def update_widget(
    *,
    widget: ReportPageAssignment,
    target_page: DashboardPage | None,
    requested_order: int | None,
    widget_type: str | None = None,
    x: int | None = None,
    y: int | None = None,
    width: int | None = None,
    height: int | None = None,
    layout_metadata: dict | None = None,
    widget_config: dict | None = None,
) -> ReportPageAssignment:
    extended_widget_schema = dashboard_widget_columns_ready()
    source_page_id = widget.page_id
    destination_page = target_page or widget.page
    destination_page_id = destination_page.id

    if extended_widget_schema and widget_type is not None:
        widget.widget_type = widget_type
    if extended_widget_schema and x is not None:
        widget.x = x
    if extended_widget_schema and y is not None:
        widget.y = y
    if extended_widget_schema and width is not None:
        widget.width = width
    if extended_widget_schema and height is not None:
        widget.height = height
    if extended_widget_schema and layout_metadata is not None:
        widget.layout_metadata = _clone_json(layout_metadata)
    if extended_widget_schema and widget_config is not None:
        widget.widget_config = _clone_json(widget_config)

    if source_page_id != destination_page_id:
        source_widgets = _locked_page_widgets(source_page_id)
        destination_widgets = _locked_page_widgets(destination_page_id)
        _persist_widget_order(source_widgets)
        _persist_widget_order(destination_widgets)

        source_ids = [row.id for row in source_widgets if row.id != widget.id]
        destination_ids = [row.id for row in destination_widgets]
        insert_at = _clamp_insert_index(requested_order, len(destination_ids))
        destination_ids.insert(insert_at, widget.id)

        source_widget_map = {row.id: row for row in source_widgets if row.id}
        destination_widget_map = {row.id: row for row in destination_widgets if row.id}

        source_dirty: list[ReportPageAssignment] = []
        for idx, row_id in enumerate(source_ids):
            row = source_widget_map.get(row_id)
            if row and row.order != idx:
                row.order = idx
                source_dirty.append(row)
        if source_dirty:
            ReportPageAssignment.objects.bulk_update(source_dirty, ["order"])

        destination_dirty: list[ReportPageAssignment] = []
        for idx, row_id in enumerate(destination_ids):
            if row_id == widget.id:
                continue
            row = destination_widget_map.get(row_id)
            if row and row.order != idx:
                row.order = idx
                destination_dirty.append(row)
        if destination_dirty:
            ReportPageAssignment.objects.bulk_update(destination_dirty, ["order"])

        widget.page = destination_page
        widget.order = insert_at
    elif requested_order is not None:
        page_widgets = _locked_page_widgets(source_page_id)
        _persist_widget_order(page_widgets)

        ids = [row.id for row in page_widgets if row.id != widget.id]
        insert_at = _clamp_insert_index(requested_order, len(ids))
        ids.insert(insert_at, widget.id)

        widget_map = {row.id: row for row in page_widgets if row.id}
        dirty: list[ReportPageAssignment] = []
        for idx, row_id in enumerate(ids):
            if row_id == widget.id:
                continue
            row = widget_map.get(row_id)
            if row and row.order != idx:
                row.order = idx
                dirty.append(row)
        if dirty:
            ReportPageAssignment.objects.bulk_update(dirty, ["order"])

        widget.order = insert_at

    widget.save()
    return widget


@transaction.atomic
def delete_widget(*, widget: ReportPageAssignment) -> None:
    page_id = widget.page_id
    widget_id = widget.id
    widget.delete()

    widgets = _locked_page_widgets(page_id)
    widgets = [row for row in widgets if row.id != widget_id]
    _persist_widget_order(widgets)
