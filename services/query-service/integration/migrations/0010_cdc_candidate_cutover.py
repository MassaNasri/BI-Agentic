from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("integration", "0009_cdc_snapshot_signal")]

    operations = [
        migrations.AddField("cdcgeneration", "cutover_phase", models.CharField(max_length=24, default="NONE")),
        migrations.AddField("cdcgeneration", "validation_certificate", models.JSONField(default=dict)),
        migrations.AddField("cdcgeneration", "candidate_ready_at", models.DateTimeField(null=True)),
        migrations.AddField("cdcgeneration", "cutover_attempted_at", models.DateTimeField(null=True)),
        migrations.AddField("cdcgeneration", "query_bound_at", models.DateTimeField(null=True)),
        migrations.AddField("cdcgeneration", "failed_at", models.DateTimeField(null=True)),
        migrations.AddConstraint("cdcgeneration", models.UniqueConstraint(fields=["pipeline"], condition=Q(state="ACTIVE"), name="cdc_one_active_generation")),
        migrations.AddConstraint("cdcgeneration", models.UniqueConstraint(fields=["pipeline"], condition=Q(state="CANDIDATE"), name="cdc_one_candidate_generation")),
    ]
