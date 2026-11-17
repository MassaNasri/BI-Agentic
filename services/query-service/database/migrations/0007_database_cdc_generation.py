from django.db import migrations, models


def stamp_existing_cdc(apps, schema_editor):
    apps.get_model("database", "Database").objects.filter(
        source_kind="cdc", etl_status="completed", cdc_generation__isnull=True,
    ).update(cdc_generation=1)


class Migration(migrations.Migration):
    dependencies = [("database", "0006_dataset_source")]
    operations = [
        migrations.AddField("database", "cdc_generation", models.PositiveIntegerField(blank=True, null=True)),
        migrations.RunPython(stamp_existing_cdc, migrations.RunPython.noop),
    ]
