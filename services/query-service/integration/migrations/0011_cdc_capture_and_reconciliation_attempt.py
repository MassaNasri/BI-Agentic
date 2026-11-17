from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integration", "0010_cdc_candidate_cutover")]

    operations = [
        migrations.AddField(
            model_name="cdcpipeline", name="capture_slot_seen",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="cdcpipeline", name="capture_ready",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="cdcgeneration", name="reconciliation_attempt",
            field=models.JSONField(default=dict),
        ),
    ]
