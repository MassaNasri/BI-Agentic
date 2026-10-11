import uuid

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [('database', '0003_database_ingestion_job_id')]

    operations = [
        migrations.CreateModel(
            name='AuthorizedQueryDefinition',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('workspace_id', models.PositiveBigIntegerField(db_index=True)),
                ('dataset_id', models.PositiveBigIntegerField(db_index=True)),
                ('normalized_sql', models.TextField()),
                ('creator_id', models.CharField(max_length=128)),
                ('validation_status', models.CharField(default='approved', max_length=20)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('expires_at', models.DateTimeField(db_index=True)),
            ],
            options={
                'db_table': 'authorized_query_definitions',
                'indexes': [models.Index(fields=['workspace_id', 'dataset_id', 'validation_status'], name='authorized__workspa_af5518_idx')],
            },
        ),
    ]
