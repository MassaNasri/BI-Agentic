import uuid

from django.db import migrations, models


def _backfill(apps, schema_editor):
    Database = apps.get_model("database", "Database")
    for row in Database.objects.filter(ingestion_job_id__isnull=True).only("pk"):
        row.ingestion_job_id = uuid.uuid4()
        row.save(update_fields=["ingestion_job_id"])


class Migration(migrations.Migration):
    dependencies = [("database", "0002_database_manager_email_database_manager_name_and_more")]

    operations = [
        migrations.AddField(
            model_name="database",
            name="ingestion_job_id",
            # Do not put a callable default on the initial PostgreSQL ALTER.
            # PostgreSQL evaluates that default once for the statement, which
            # gives every pre-existing row the same UUID and breaks the later
            # unique constraint. Add NULL, backfill row-by-row, then constrain.
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(_backfill, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="database",
            name="ingestion_job_id",
            field=models.UUIDField(
                db_index=True,
                default=uuid.uuid4,
                editable=False,
                help_text="Immutable query-service-owned ingestion job identifier.",
                unique=True,
            ),
        ),
    ]
