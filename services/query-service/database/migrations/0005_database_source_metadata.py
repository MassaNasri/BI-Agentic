from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("database", "0004_authorizedquerydefinition")]

    operations = [
        migrations.AddField(
            model_name="database",
            name="source_kind",
            field=models.CharField(default="file", max_length=20),
        ),
        migrations.AddField(
            model_name="database",
            name="source_engine",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.AddField(
            model_name="database",
            name="source_tables",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
