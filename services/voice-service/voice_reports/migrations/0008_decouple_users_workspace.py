from django.db import migrations, models


OWNERSHIP_COLUMN_TARGETS = {
    "voice_reports": {"workspace_id", "created_by_id", "edited_by_id"},
    "dashboard_pages": {"workspace_id", "created_by_id"},
    "sql_edit_history": {"edited_by_id"},
    "report_page_assignments": {"added_by_id"},
    "voice_pipeline_jobs": {"workspace_id", "user_id"},
}


def _drop_legacy_single_column_indexes(apps, schema_editor):
    """
    Some environments still have legacy auto-generated single-column indexes
    (from older FK/field states) that collide with the new db_index creation
    during AlterField. Drop only non-unique, non-PK single-column indexes for
    the targeted columns so AlterField can recreate the expected index safely.
    """

    connection = schema_editor.connection
    introspection = connection.introspection
    quote = schema_editor.quote_name

    with connection.cursor() as cursor:
        for table_name, columns in OWNERSHIP_COLUMN_TARGETS.items():
            constraints = introspection.get_constraints(cursor, table_name)
            for name, data in constraints.items():
                if not data.get("index"):
                    continue
                if data.get("unique") or data.get("primary_key"):
                    continue
                index_columns = data.get("columns") or []
                if len(index_columns) != 1:
                    continue
                if index_columns[0] not in columns:
                    continue
                schema_editor.execute(f"DROP INDEX IF EXISTS {quote(name)}")


def _coerce_legacy_ownership_columns_to_varchar(apps, schema_editor):
    """
    Some environments still have bigint FK ownership columns from the pre-
    decoupling schema while migration state expects text-backed IDs.

    Force those physical columns to varchar(64) before AlterField so Django's
    later index operations (including varchar_pattern_ops) apply to the right
    data type.
    """

    textual_udt_names = {"varchar", "text", "bpchar", "citext"}
    connection = schema_editor.connection
    introspection = connection.introspection
    quote = schema_editor.quote_name

    with connection.cursor() as cursor:
        for table_name, columns in OWNERSHIP_COLUMN_TARGETS.items():
            constraints = introspection.get_constraints(cursor, table_name)

            for name, data in constraints.items():
                constraint_columns = data.get("columns") or []
                if not data.get("foreign_key"):
                    continue
                if len(constraint_columns) != 1:
                    continue
                if constraint_columns[0] not in columns:
                    continue
                schema_editor.execute(
                    f"ALTER TABLE {quote(table_name)} DROP CONSTRAINT IF EXISTS {quote(name)}"
                )

            for column_name in columns:
                cursor.execute(
                    """
                    SELECT udt_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND table_name = %s
                      AND column_name = %s
                    """,
                    [table_name, column_name],
                )
                row = cursor.fetchone()
                if not row:
                    continue
                udt_name = str(row[0] or "").lower()
                if udt_name in textual_udt_names:
                    continue
                schema_editor.execute(
                    f"ALTER TABLE {quote(table_name)} "
                    f"ALTER COLUMN {quote(column_name)} TYPE varchar(64) "
                    f"USING {quote(column_name)}::varchar(64)"
                )


def _noop_reverse(apps, schema_editor):
    # Reverse is intentionally a no-op; AlterField will recreate expected
    # indexes for the current schema state.
    return


class Migration(migrations.Migration):
    dependencies = [
        ("voice_reports", "0007_voicepipelinejob"),
    ]

    operations = [
        migrations.RenameField(
            model_name="voicereport",
            old_name="workspace",
            new_name="workspace_id",
        ),
        migrations.RenameField(
            model_name="voicereport",
            old_name="created_by",
            new_name="created_by_id",
        ),
        migrations.RenameField(
            model_name="voicereport",
            old_name="edited_by",
            new_name="edited_by_id",
        ),
        migrations.RenameField(
            model_name="dashboardpage",
            old_name="workspace",
            new_name="workspace_id",
        ),
        migrations.RenameField(
            model_name="dashboardpage",
            old_name="created_by",
            new_name="created_by_id",
        ),
        migrations.RenameField(
            model_name="sqledithistory",
            old_name="edited_by",
            new_name="edited_by_id",
        ),
        migrations.RenameField(
            model_name="reportpageassignment",
            old_name="added_by",
            new_name="added_by_id",
        ),
        migrations.RenameField(
            model_name="voicepipelinejob",
            old_name="workspace",
            new_name="workspace_id",
        ),
        migrations.RenameField(
            model_name="voicepipelinejob",
            old_name="user",
            new_name="user_id",
        ),
        migrations.AlterModelOptions(
            name="dashboardpage",
            options={
                "ordering": ["workspace_id", "order"],
                "verbose_name": "Dashboard Page",
                "verbose_name_plural": "Dashboard Pages",
            },
        ),
        migrations.RemoveIndex(
            model_name="voicepipelinejob",
            name="voice_pipel_workspa_621303_idx",
        ),
        migrations.RemoveIndex(
            model_name="voicepipelinejob",
            name="voice_pipel_user_id_f6202c_idx",
        ),
        migrations.RemoveIndex(
            model_name="voicereport",
            name="voice_repor_workspa_bcddb4_idx",
        ),
        migrations.RemoveIndex(
            model_name="voicereport",
            name="voice_repor_workspa_033512_idx",
        ),
        migrations.RenameIndex(
            model_name="voicepipelinejob",
            new_name="voice_pipel_report__c770bf_idx",
            old_name="voice_pipel_report__d6dd59_idx",
        ),
        migrations.AddField(
            model_name="voicereport",
            name="created_by_email",
            field=models.EmailField(blank=True, default="", max_length=254),
        ),
        migrations.AddField(
            model_name="voicereport",
            name="edited_by_email",
            field=models.EmailField(blank=True, default="", help_text="Email of user who last edited SQL", max_length=254),
        ),
        migrations.AddField(
            model_name="sqledithistory",
            name="edited_by_email",
            field=models.EmailField(blank=True, default="", max_length=254),
        ),
        migrations.AddField(
            model_name="dashboardpage",
            name="created_by_email",
            field=models.EmailField(blank=True, default="", max_length=254),
        ),
        migrations.AddField(
            model_name="reportpageassignment",
            name="added_by_email",
            field=models.EmailField(blank=True, default="", max_length=254),
        ),
        migrations.AddField(
            model_name="voicepipelinejob",
            name="user_email",
            field=models.EmailField(blank=True, default="", max_length=254),
        ),
        migrations.RunPython(
            code=_drop_legacy_single_column_indexes,
            reverse_code=_noop_reverse,
        ),
        migrations.RunPython(
            code=_coerce_legacy_ownership_columns_to_varchar,
            reverse_code=_noop_reverse,
        ),
        migrations.AlterField(
            model_name="voicereport",
            name="workspace_id",
            field=models.CharField(db_index=True, max_length=64),
        ),
        migrations.AlterField(
            model_name="voicereport",
            name="created_by_id",
            field=models.CharField(db_index=True, max_length=64),
        ),
        migrations.AlterField(
            model_name="voicereport",
            name="edited_by_id",
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name="dashboardpage",
            name="workspace_id",
            field=models.CharField(db_index=True, max_length=64),
        ),
        migrations.AlterField(
            model_name="dashboardpage",
            name="created_by_id",
            field=models.CharField(db_index=True, max_length=64),
        ),
        migrations.AlterField(
            model_name="sqledithistory",
            name="edited_by_id",
            field=models.CharField(db_index=True, max_length=64),
        ),
        migrations.AlterField(
            model_name="reportpageassignment",
            name="added_by_id",
            field=models.CharField(db_index=True, max_length=64),
        ),
        migrations.AlterField(
            model_name="voicepipelinejob",
            name="workspace_id",
            field=models.CharField(db_index=True, max_length=64),
        ),
        migrations.AlterField(
            model_name="voicepipelinejob",
            name="user_id",
            field=models.CharField(db_index=True, max_length=64),
        ),
        migrations.AlterField(
            model_name="voicereport",
            name="chart_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("line", "Line Chart"),
                    ("line_multi", "Multi-Line Chart"),
                    ("bar", "Bar Chart"),
                    ("bar_grouped", "Grouped Bar Chart"),
                    ("bar_stacked", "Stacked Bar Chart"),
                    ("pie", "Pie Chart"),
                    ("area", "Area Chart"),
                    ("map", "Map"),
                    ("combo_line_bar", "Combo Line/Bar Chart"),
                    ("card", "Card"),
                    ("table", "Table"),
                    ("scatter", "Scatter Plot"),
                    ("histogram", "Histogram"),
                    ("kpi", "Legacy KPI"),
                    ("number", "Legacy Number/KPI"),
                    ("scalar", "Legacy Scalar"),
                    ("grouped_bar", "Legacy Grouped Bar"),
                    ("stacked_bar", "Legacy Stacked Bar"),
                    ("combo", "Legacy Combo"),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="voicepipelinejob",
            name="status",
            field=models.CharField(
                choices=[
                    ("PENDING", "Pending"),
                    ("QUEUED", "Queued"),
                    ("TRANSCRIBING", "Transcribing"),
                    ("AI_PROCESSING", "AI Processing"),
                    ("SQL_GENERATED", "SQL Generated"),
                    ("EXECUTING_QUERY", "Executing Query"),
                    ("VISUALIZING", "Visualizing"),
                    ("COMPLETED", "Completed"),
                    ("FAILED", "Failed"),
                    ("PARTIAL", "Partial"),
                ],
                default="PENDING",
                max_length=32,
            ),
        ),
        migrations.AddIndex(
            model_name="voicepipelinejob",
            index=models.Index(fields=["workspace_id", "status"], name="voice_pipel_workspa_d84b57_idx"),
        ),
        migrations.AddIndex(
            model_name="voicepipelinejob",
            index=models.Index(fields=["user_id", "status"], name="voice_pipel_user_id_eb6dc8_idx"),
        ),
        migrations.AddIndex(
            model_name="voicereport",
            index=models.Index(fields=["workspace_id", "created_by_id"], name="voice_repor_workspa_bcddb4_idx"),
        ),
        migrations.AddIndex(
            model_name="voicereport",
            index=models.Index(fields=["workspace_id", "status"], name="voice_repor_workspa_033512_idx"),
        ),
    ]
