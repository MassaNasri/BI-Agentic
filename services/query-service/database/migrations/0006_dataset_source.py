from django.db import migrations, models
import django.db.models.deletion


def backfill_sources(apps, schema_editor):
    Dataset = apps.get_model("database", "Database")
    Source = apps.get_model("integration", "DataSource")
    alias = schema_editor.connection.alias
    rows = Dataset.objects.using(alias).filter(source_kind="database", workspace_id__isnull=False)
    for dataset in rows.iterator():
        selected = []
        for table in dataset.source_tables or []:
            if isinstance(table, dict) and table.get("name"):
                selected.append({"schema": table.get("schema"), "name": table["name"]})
        source, _ = Source.objects.using(alias).get_or_create(
            legacy_dataset_id=dataset.pk,
            defaults={
                "workspace_id": dataset.workspace_id,
                "created_by": dataset.manager,
                "name": dataset.filename,
                "engine": dataset.source_engine or "unknown",
                "selected_tables": selected,
                "created_at": dataset.upload_date,
            },
        )
        Dataset.objects.using(alias).filter(pk=dataset.pk).update(source_id=source.pk)


def unlink_backfill(apps, schema_editor):
    # Removing the FK in the reverse migration does not delete source history.
    # The integration migration owns its eventual table removal.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("integration", "0001_initial"),
        ("database", "0005_database_source_metadata"),
    ]

    operations = [
        migrations.AlterField(
            model_name="database", name="manager",
            field=models.PositiveBigIntegerField(db_column="manager_id", db_index=True,
                help_text="Manager user identifier from auth-service."),
        ),
        migrations.AddField(
            model_name="database", name="source",
            field=models.ForeignKey(blank=True, help_text="Integration-owned source; file uploads have no persistent source.",
                null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="datasets", to="integration.datasource"),
        ),
        migrations.RunPython(backfill_sources, unlink_backfill),
    ]
