# Generated manually on 2025-11-28
# Migration to fix invitation system: allow re-invitations after removal

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workspace", "0002_alter_workspacemember_unique_together_and_more"),
    ]

    operations = [
        # Remove the old unique_together constraint that prevented re-invitations
        migrations.AlterUniqueTogether(
            name="invitation",
            unique_together=set(),
        ),
        # Add a new constraint that only prevents duplicate PENDING invitations
        # This allows re-inviting users after they were removed or after invitations expired
        migrations.AddConstraint(
            model_name='invitation',
            constraint=models.UniqueConstraint(
                fields=['invited_email', 'workspace'],
                condition=models.Q(status='pending'),
                name='unique_pending_invitation'
            ),
        ),
    ]

