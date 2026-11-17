from django.db import migrations, models
import django.utils.timezone
import uuid


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="DataSource",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("legacy_dataset_id", models.PositiveBigIntegerField(blank=True, null=True, unique=True)),
                ("workspace_id", models.PositiveBigIntegerField(db_index=True)),
                ("created_by", models.PositiveBigIntegerField()),
                ("name", models.CharField(max_length=255)),
                ("engine", models.CharField(max_length=32)),
                ("connection_metadata", models.JSONField(blank=True, default=dict)),
                ("selected_tables", models.JSONField(blank=True, default=list)),
                ("state", models.CharField(choices=[("active", "Active"), ("disabled", "Disabled"), ("retired", "Retired")], default="active", max_length=16)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "integration_data_sources"},
        ),
        migrations.AddIndex(
            model_name="datasource",
            index=models.Index(fields=["workspace_id", "state"], name="source_workspace_state_idx"),
        ),
    ]
