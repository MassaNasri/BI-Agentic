"""Reconcile Voice model state without unnecessary database DDL.

The two dashboard indexes already exist under the explicit names retained in
the model. chart_type keeps the same PostgreSQL varchar(20) definition; only
its Django choices metadata changed.
"""

from django.db import migrations, models


CHART_CHOICES = [
    ("line", "Line Chart"),
    ("line_multi", "Multi-Series Line Chart"),
    ("cumulative_line", "Cumulative Line Chart"),
    ("bar", "Bar Chart"),
    ("bar_grouped", "Grouped Bar Chart"),
    ("bar_stacked", "Stacked Bar Chart"),
    ("pie", "Pie Chart"),
    ("area", "Area Chart"),
    ("card", "Card"),
    ("table", "Table"),
    ("scatter", "Scatter Plot"),
    ("histogram", "Histogram"),
    ("combo_line_bar", "Combo Line-Bar Chart"),
    ("map", "Map Chart"),
    ("heatmap", "Heatmap"),
    ("kpi", "Legacy KPI"),
    ("pie", "Legacy Pie"),
    ("number", "Legacy Number/KPI"),
    ("scalar", "Legacy Scalar"),
    ("grouped_bar", "Legacy Grouped Bar"),
]


class Migration(migrations.Migration):
    dependencies = [
        ("voice_reports", "0012_add_visualization_spec"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name="voicereport",
                    name="chart_type",
                    field=models.CharField(
                        blank=True,
                        choices=CHART_CHOICES,
                        max_length=20,
                    ),
                ),
            ],
        ),
    ]
