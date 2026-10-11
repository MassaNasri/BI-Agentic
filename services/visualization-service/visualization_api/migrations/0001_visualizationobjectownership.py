from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name='VisualizationObjectOwnership',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('workspace_id', models.PositiveBigIntegerField(db_index=True)),
                ('object_type', models.CharField(choices=[('card', 'Card'), ('dashboard', 'Dashboard')], max_length=16)),
                ('metabase_object_id', models.PositiveBigIntegerField()),
                ('creator_id', models.CharField(max_length=128)),
                ('query_definition_id', models.UUIDField(blank=True, null=True)),
                ('source_context', models.JSONField(blank=True, default=dict)),
                ('ownership_status', models.CharField(choices=[('mapped', 'Mapped'), ('unmapped', 'Unmapped')], default='mapped', max_length=16)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                'db_table': 'visualization_object_ownership',
                'indexes': [models.Index(fields=['workspace_id', 'object_type', 'ownership_status'], name='visualizati_workspa_5b3fe8_idx')],
                'constraints': [models.UniqueConstraint(fields=('object_type', 'metabase_object_id'), name='unique_metabase_object_ownership')],
            },
        )
    ]
