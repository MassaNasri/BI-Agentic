from django.db import migrations


DEFAULT_WIDGET_WIDTH = 6
DEFAULT_WIDGET_HEIGHT = 4
GRID_COLUMNS = 12


def _widget_position_for_order(order_index: int) -> tuple[int, int]:
    widgets_per_row = max(1, GRID_COLUMNS // DEFAULT_WIDGET_WIDTH)
    column_index = order_index % widgets_per_row
    row_index = order_index // widgets_per_row
    return column_index * DEFAULT_WIDGET_WIDTH, row_index * DEFAULT_WIDGET_HEIGHT


def _seed_dashboard_builder(apps, schema_editor):
    VoiceReport = apps.get_model("voice_reports", "VoiceReport")
    DashboardPage = apps.get_model("voice_reports", "DashboardPage")
    ReportPageAssignment = apps.get_model("voice_reports", "ReportPageAssignment")

    workspace_ids = (
        VoiceReport.objects.exclude(workspace_id__isnull=True)
        .exclude(workspace_id="")
        .values_list("workspace_id", flat=True)
        .distinct()
    )

    for workspace_id in workspace_ids:
        pages = list(
            DashboardPage.objects.filter(workspace_id=workspace_id).order_by("order", "id")
        )

        if not pages:
            report_owner = (
                VoiceReport.objects.filter(workspace_id=workspace_id)
                .order_by("created_at", "id")
                .values("created_by_id", "created_by_email")
                .first()
                or {}
            )
            first_page = DashboardPage.objects.create(
                workspace_id=workspace_id,
                name="Page 1",
                description="Auto-created during dashboard builder migration.",
                order=0,
                created_by_id=report_owner.get("created_by_id") or "system",
                created_by_email=report_owner.get("created_by_email") or "",
            )
            pages = [first_page]

        primary_page = pages[0]

        existing_primary_widgets = list(
            ReportPageAssignment.objects.filter(page_id=primary_page.id).order_by("order", "id")
        )
        dirty_primary_widgets = []
        for index, widget in enumerate(existing_primary_widgets):
            if widget.order != index:
                widget.order = index
                dirty_primary_widgets.append(widget)
        if dirty_primary_widgets:
            ReportPageAssignment.objects.bulk_update(dirty_primary_widgets, ["order"])

        assigned_report_ids = set(
            ReportPageAssignment.objects.filter(page__workspace_id=workspace_id).values_list("report_id", flat=True)
        )

        workspace_reports = list(
            VoiceReport.objects.filter(workspace_id=workspace_id)
            .order_by("created_at", "id")
            .values("id", "created_by_id", "created_by_email")
        )

        next_order = len(existing_primary_widgets)
        pending_widgets = []
        for report in workspace_reports:
            report_id = report.get("id")
            if not report_id or report_id in assigned_report_ids:
                continue
            x, y = _widget_position_for_order(next_order)
            pending_widgets.append(
                ReportPageAssignment(
                    page_id=primary_page.id,
                    report_id=report_id,
                    widget_type="report",
                    order=next_order,
                    x=x,
                    y=y,
                    width=DEFAULT_WIDGET_WIDTH,
                    height=DEFAULT_WIDGET_HEIGHT,
                    layout_metadata={},
                    widget_config={},
                    added_by_id=report.get("created_by_id") or "system",
                    added_by_email=report.get("created_by_email") or "",
                )
            )
            next_order += 1

        if pending_widgets:
            ReportPageAssignment.objects.bulk_create(pending_widgets, batch_size=500)


def _noop_reverse(apps, schema_editor):
    return


class Migration(migrations.Migration):
    dependencies = [
        ("voice_reports", "0010_dashboard_builder_foundation"),
    ]

    operations = [
        migrations.RunPython(_seed_dashboard_builder, _noop_reverse),
    ]

