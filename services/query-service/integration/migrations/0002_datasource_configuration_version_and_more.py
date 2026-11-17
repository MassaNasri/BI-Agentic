import django.db.models.deletion
import django.utils.timezone
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('integration', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='datasource',
            name='configuration_version',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='datasource',
            name='transport',
            field=models.CharField(default='direct_secure_internet', max_length=48),
        ),
        migrations.CreateModel(
            name='SourceCredential',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('version', models.PositiveIntegerField()),
                ('key_version', models.CharField(max_length=8)),
                ('ciphertext', models.TextField()),
                ('state', models.CharField(default='candidate', max_length=16)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('activated_at', models.DateTimeField(blank=True, null=True)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
                ('source', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='credentials', to='integration.datasource')),
            ],
            options={
                'db_table': 'integration_source_credentials',
            },
        ),
        migrations.CreateModel(
            name='SourceCandidate',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('engine', models.CharField(max_length=32)),
                ('connection_metadata', models.JSONField(default=dict)),
                ('selected_tables', models.JSONField(default=list)),
                ('state', models.CharField(default='staged', max_length=16)),
                ('validation_dataset_id', models.PositiveBigIntegerField(null=True)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('source', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='candidate', to='integration.datasource')),
                ('credential', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='integration.sourcecredential')),
            ],
            options={
                'db_table': 'integration_source_candidates',
            },
        ),
        migrations.CreateModel(
            name='SourceExecution',
            fields=[
                ('job_id', models.UUIDField(primary_key=True, serialize=False)),
                ('workspace_id', models.PositiveBigIntegerField()),
                ('dataset_id', models.CharField(max_length=128)),
                ('kind', models.CharField(max_length=16)),
                ('engine', models.CharField(max_length=32)),
                ('configuration_version', models.PositiveIntegerField()),
                ('connection_metadata', models.JSONField(default=dict)),
                ('transport', models.CharField(max_length=48)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('expires_at', models.DateTimeField()),
                ('credential', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='integration.sourcecredential')),
                ('source', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='integration.datasource')),
            ],
            options={
                'db_table': 'integration_source_executions',
            },
        ),
        migrations.AddConstraint(
            model_name='sourcecredential',
            constraint=models.UniqueConstraint(fields=('source', 'version'), name='source_credential_version_uniq'),
        ),
    ]
