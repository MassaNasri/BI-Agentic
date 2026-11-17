from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integration", "0008_cdc_controller_lease")]

    operations = [
        migrations.AddField(model_name="cdcpipeline", name="snapshot_signal",
                            field=models.JSONField(default=dict)),
        migrations.AddField(model_name="cdcgeneration", name="snapshot_signal",
                            field=models.JSONField(default=dict)),
    ]
