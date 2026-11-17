from django.db import migrations, models
from django.utils import timezone
import django.db.models.deletion


def backfill_existing_lineages(apps, schema_editor):
    Pipeline = apps.get_model("integration", "CdcPipeline")
    Generation = apps.get_model("integration", "CdcGeneration")
    alias = schema_editor.connection.alias
    for pipeline in Pipeline.objects.using(alias).iterator():
        Generation.objects.using(alias).create(
            pipeline_id=pipeline.pk, number=1,
            state="RESEED_REQUIRED" if pipeline.observed_state == "RESEED_REQUIRED" else "ACTIVE",
            workspace_id=pipeline.workspace_id, source_id=pipeline.source_id,
            dataset_id=pipeline.dataset_id, table_schema=pipeline.table_schema,
            table_name=pipeline.table_name, schema_version=pipeline.schema_version,
            columns=pipeline.columns, primary_key=pipeline.primary_key,
            checkpoints=pipeline.checkpoints, reason=pipeline.error_code,
            created_at=pipeline.created_at)


class Migration(migrations.Migration):
    dependencies = [("integration", "0006_cdcaudit_dataset_id_cdcaudit_new_desired_state_and_more")]

    operations = [
        migrations.AddField(
            model_name="cdcpipeline", name="generation",
            field=models.PositiveIntegerField(default=1)),
        migrations.CreateModel(
            name="CdcGeneration",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("number", models.PositiveIntegerField()),
                ("state", models.CharField(choices=[(value, value) for value in
                    ("ACTIVE", "CANDIDATE", "SUPERSEDED", "FAILED", "RESEED_REQUIRED")], max_length=24)),
                ("workspace_id", models.PositiveBigIntegerField()),
                ("source_id", models.UUIDField()),
                ("dataset_id", models.PositiveBigIntegerField()),
                ("table_schema", models.CharField(max_length=63)),
                ("table_name", models.CharField(max_length=63)),
                ("schema_version", models.PositiveIntegerField(default=1)),
                ("columns", models.JSONField(default=list)),
                ("primary_key", models.JSONField(default=list)),
                ("checkpoints", models.JSONField(default=dict)),
                ("previous_number", models.PositiveIntegerField(null=True)),
                ("reason", models.CharField(blank=True, max_length=64)),
                ("created_at", models.DateTimeField(default=timezone.now)),
                ("superseded_at", models.DateTimeField(null=True)),
                ("pipeline", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                    related_name="generations", to="integration.cdcpipeline")),
            ], options={"db_table": "integration_cdc_generations"}),
        migrations.AddConstraint(
            model_name="cdcgeneration",
            constraint=models.UniqueConstraint(fields=("pipeline", "number"),
                name="cdc_generation_number_uniq")),
        migrations.RunPython(backfill_existing_lineages, migrations.RunPython.noop),
    ]
