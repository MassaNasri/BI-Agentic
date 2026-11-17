from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('integration', '0002_datasource_configuration_version_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='sourcecandidate',
            name='cutover_at',
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name='sourcecredential',
            name='deactivated_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
