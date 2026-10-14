from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("voice_reports", "0013_reconcile_chart_type_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="voicereport",
            name="dataset_id",
            field=models.PositiveBigIntegerField(
                blank=True,
                db_index=True,
                help_text="Logical Query-service dataset identifier used for authorization",
                null=True,
            ),
        ),
    ]
