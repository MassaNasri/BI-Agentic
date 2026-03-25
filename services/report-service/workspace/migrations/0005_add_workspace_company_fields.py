# Generated manually to extend workspace edit metadata.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('workspace', '0004_remove_old_invitation_constraint'),
    ]

    operations = [
        migrations.AddField(
            model_name='workspace',
            name='company_address',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='workspace',
            name='company_number',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
    ]
