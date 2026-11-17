from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("integration", "0007_cdc_generation")]

    operations = [
        migrations.AddField(model_name="cdcpipeline", name="controller_lease_owner",
                            field=models.UUIDField(null=True)),
        migrations.AddField(model_name="cdcpipeline", name="controller_lease_until",
                            field=models.DateTimeField(null=True)),
        migrations.AddField(model_name="cdcpipeline", name="controller_fence",
                            field=models.PositiveIntegerField(default=0)),
    ]
