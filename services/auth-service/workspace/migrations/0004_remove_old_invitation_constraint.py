# Generated manually on 2025-11-28
# Migration to remove old invitation constraint that blocks re-invitations

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("workspace", "0003_remove_invitation_unique_together_and_add_constraint"),
    ]

    operations = [
        # Remove the old constraint that includes status
        # This constraint was preventing re-invitations
        migrations.RunSQL(
            # Drop the old constraint
            sql="""
                ALTER TABLE invitations 
                DROP CONSTRAINT IF EXISTS invitations_invited_email_workspace_id_status_21a6ec8e_uniq;
            """,
            # Reverse SQL (recreate if rollback)
            reverse_sql="""
                ALTER TABLE invitations 
                ADD CONSTRAINT invitations_invited_email_workspace_id_status_21a6ec8e_uniq 
                UNIQUE (invited_email, workspace_id, status);
            """
        ),
    ]

