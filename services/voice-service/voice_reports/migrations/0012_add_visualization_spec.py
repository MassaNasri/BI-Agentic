from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("voice_reports", "0011_backfill_dashboard_builder_seed"),
    ]

    operations = [
        migrations.AddField(
            model_name="voicereport",
            name="visualization_spec",
            field=models.JSONField(
                blank=True,
                help_text="Complete VisualizationSpec contract for rendering and chart switching",
                null=True,
            ),
        ),
    ]
