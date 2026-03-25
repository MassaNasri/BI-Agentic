# Generated manually to extend user profile and password reset workflow.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


def _add_column_if_missing(name, sql_type, field):
    return migrations.SeparateDatabaseAndState(
        database_operations=[
            migrations.RunSQL(
                sql=f'ALTER TABLE "users" ADD COLUMN IF NOT EXISTS "{name}" {sql_type};',
                reverse_sql=f'ALTER TABLE "users" DROP COLUMN IF EXISTS "{name}";',
            ),
        ],
        state_operations=[
            migrations.AddField(
                model_name='user',
                name=name,
                field=field,
            ),
        ],
    )


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        _add_column_if_missing(
            name='date_of_birth',
            sql_type='date NULL',
            field=models.DateField(blank=True, null=True),
        ),
        _add_column_if_missing(
            name='first_name',
            sql_type="character varying(150) NOT NULL DEFAULT ''",
            field=models.CharField(blank=True, default='', max_length=150),
        ),
        _add_column_if_missing(
            name='home_address',
            sql_type="text NOT NULL DEFAULT ''",
            field=models.TextField(blank=True, default=''),
        ),
        _add_column_if_missing(
            name='last_name',
            sql_type="character varying(150) NOT NULL DEFAULT ''",
            field=models.CharField(blank=True, default='', max_length=150),
        ),
        migrations.CreateModel(
            name='PasswordResetCode',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(db_index=True, max_length=254)),
                ('code_hash', models.CharField(max_length=255)),
                ('verification_token', models.UUIDField(db_index=True, default=uuid.uuid4, unique=True)),
                ('expires_at', models.DateTimeField()),
                ('is_verified', models.BooleanField(default=False)),
                ('is_used', models.BooleanField(default=False)),
                ('attempts', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('verified_at', models.DateTimeField(blank=True, null=True)),
                (
                    'user',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='password_reset_codes',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'db_table': 'password_reset_codes',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='passwordresetcode',
            index=models.Index(fields=['email', 'is_used'], name='password_re_email_994d9f_idx'),
        ),
        migrations.AddIndex(
            model_name='passwordresetcode',
            index=models.Index(fields=['user', 'is_used'], name='password_re_user_id_51447f_idx'),
        ),
        migrations.AddIndex(
            model_name='passwordresetcode',
            index=models.Index(fields=['expires_at'], name='password_re_expires_b5be6c_idx'),
        ),
    ]
