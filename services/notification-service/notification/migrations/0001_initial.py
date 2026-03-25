# Generated manually for notification dispatch tracking table.

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='NotificationDispatchLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(max_length=100)),
                ('event_key', models.CharField(max_length=255)),
                ('recipient_email', models.EmailField(max_length=254)),
                (
                    'status',
                    models.CharField(
                        choices=[
                            ('pending', 'Pending'),
                            ('sent', 'Sent'),
                            ('failed', 'Failed'),
                            ('skipped', 'Skipped'),
                        ],
                        default='pending',
                        max_length=20,
                    ),
                ),
                ('payload', models.JSONField(blank=True, default=dict)),
                ('error_message', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'db_table': 'notification_dispatch_logs',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='notificationdispatchlog',
            constraint=models.UniqueConstraint(
                fields=('event_type', 'event_key', 'recipient_email'),
                name='notification_dispatch_unique_event_recipient',
            ),
        ),
    ]
