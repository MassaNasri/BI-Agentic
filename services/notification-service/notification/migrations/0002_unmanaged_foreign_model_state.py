"""Record Notification's foreign read models without creating their tables.

These unmanaged models map tables owned by Auth, Workspace, and Subscription.
P0-B intentionally reconciles Django state only; Notification must not create,
alter, or own those physical tables.
"""

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("notification", "0001_initial"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name="PlanRecord",
                    fields=[
                        (
                            "id",
                            models.BigIntegerField(
                                primary_key=True,
                                serialize=False,
                            ),
                        ),
                        ("name", models.CharField(max_length=120)),
                        (
                            "duration_days",
                            models.PositiveIntegerField(default=30),
                        ),
                    ],
                    options={
                        "db_table": "subscription_plans",
                        "managed": False,
                    },
                ),
                migrations.CreateModel(
                    name="SubscriptionRecord",
                    fields=[
                        (
                            "id",
                            models.BigIntegerField(
                                primary_key=True,
                                serialize=False,
                            ),
                        ),
                        ("workspace_id", models.BigIntegerField()),
                        ("start_date", models.DateField()),
                        (
                            "end_date",
                            models.DateField(blank=True, null=True),
                        ),
                        ("is_active", models.BooleanField(default=True)),
                        (
                            "created_at",
                            models.DateTimeField(
                                default=django.utils.timezone.now,
                            ),
                        ),
                    ],
                    options={
                        "db_table": "workspace_subscriptions",
                        "managed": False,
                    },
                ),
                migrations.CreateModel(
                    name="UserRecord",
                    fields=[
                        (
                            "id",
                            models.BigIntegerField(
                                primary_key=True,
                                serialize=False,
                            ),
                        ),
                        ("name", models.CharField(max_length=255)),
                        ("email", models.EmailField(max_length=254)),
                        ("role", models.CharField(max_length=20)),
                        ("is_verified", models.BooleanField(default=False)),
                        ("is_active", models.BooleanField(default=True)),
                    ],
                    options={
                        "db_table": "users",
                        "managed": False,
                    },
                ),
                migrations.CreateModel(
                    name="WorkspaceMemberRecord",
                    fields=[
                        (
                            "id",
                            models.BigIntegerField(
                                primary_key=True,
                                serialize=False,
                            ),
                        ),
                        (
                            "invited_email",
                            models.EmailField(
                                blank=True,
                                max_length=254,
                                null=True,
                            ),
                        ),
                        ("role", models.CharField(max_length=20)),
                        ("status", models.CharField(max_length=30)),
                        (
                            "joined_at",
                            models.DateTimeField(blank=True, null=True),
                        ),
                    ],
                    options={
                        "db_table": "workspace_members",
                        "managed": False,
                    },
                ),
                migrations.CreateModel(
                    name="WorkspaceRecord",
                    fields=[
                        (
                            "id",
                            models.BigIntegerField(
                                primary_key=True,
                                serialize=False,
                            ),
                        ),
                        ("name", models.CharField(max_length=255)),
                    ],
                    options={
                        "db_table": "workspaces",
                        "managed": False,
                    },
                ),
            ],
        ),
    ]
