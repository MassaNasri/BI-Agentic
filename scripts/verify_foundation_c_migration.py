"""Exercise the C1/C2 migration on an explicitly disposable PostgreSQL DB."""

import os

if os.environ.get("BIAVORA_MIGRATION_DISPOSABLE") != "1":
    raise SystemExit("Set BIAVORA_MIGRATION_DISPOSABLE=1 for a disposable database only.")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "service_config.settings")

import django

django.setup()

from django.db import connection  # noqa: E402
from django.db.migrations.executor import MigrationExecutor  # noqa: E402


with connection.cursor() as cursor:
    # Historical database.0002 copies labels and workspace IDs from owner
    # tables. These disposable stubs reproduce that legacy migration input.
    cursor.execute("CREATE TABLE IF NOT EXISTS users (id bigint PRIMARY KEY, email varchar(254), name varchar(255))")
    cursor.execute("CREATE TABLE IF NOT EXISTS workspaces (id bigint PRIMARY KEY, owner_id bigint)")


old_target = ("database", "0005_database_source_metadata")
new_target = ("database", "0006_dataset_source")
source_target = ("integration", "0001_initial")

executor = MigrationExecutor(connection)
executor.migrate([old_target])
old_apps = executor.loader.project_state([old_target]).apps
LegacyDataset = old_apps.get_model("database", "Database")
legacy = LegacyDataset.objects.create(
    manager=11, workspace_id=7, filename="postgresql:orders", file_size=0,
    file_path="", source_kind="database", source_engine="postgresql",
    source_tables=[{"schema": "public", "name": "orders", "destination_table": "physical_internal"}],
)

executor = MigrationExecutor(connection)
executor.migrate([new_target])
new_apps = executor.loader.project_state([new_target]).apps
Dataset = new_apps.get_model("database", "Database")
Source = new_apps.get_model("integration", "DataSource")
dataset = Dataset.objects.get(pk=legacy.pk)
source_id = dataset.source_id
assert source_id is not None
source = Source.objects.get(pk=source_id)
assert source.workspace_id == 7 and source.created_by == 11
assert source.selected_tables == [{"schema": "public", "name": "orders"}]
assert "physical_internal" not in str(source.selected_tables)

executor = MigrationExecutor(connection)
executor.migrate([old_target, source_target])
executor = MigrationExecutor(connection)
executor.migrate([new_target])
reapplied_apps = executor.loader.project_state([new_target]).apps
Dataset = reapplied_apps.get_model("database", "Database")
Source = reapplied_apps.get_model("integration", "DataSource")
assert Dataset.objects.get(pk=legacy.pk).source_id == source_id
assert Source.objects.filter(legacy_dataset_id=legacy.pk).count() == 1
print("Foundation-C migration forward/reverse/reapply: PASS")

# C3 is additive: legacy rows retain IDs and deliberately receive no fake key.
c3_target = ("integration", "0003_sourcecandidate_cutover_at_and_more")
executor = MigrationExecutor(connection)
executor.migrate([new_target, c3_target])
c3_apps = executor.loader.project_state([new_target, c3_target]).apps
assert c3_apps.get_model("database", "Database").objects.get(pk=legacy.pk).source_id == source_id
assert c3_apps.get_model("integration", "DataSource").objects.get(pk=source_id).workspace_id == 7
assert c3_apps.get_model("integration", "SourceCredential").objects.count() == 0
assert c3_apps.get_model("integration", "SourceExecution").objects.count() == 0

executor = MigrationExecutor(connection)
executor.migrate([new_target, source_target])
executor = MigrationExecutor(connection)
executor.migrate([new_target, c3_target])
reapplied = executor.loader.project_state([new_target, c3_target]).apps
assert reapplied.get_model("database", "Database").objects.get(pk=legacy.pk).source_id == source_id
assert reapplied.get_model("integration", "SourceCredential").objects.count() == 0
print("Foundation-C C3 migration forward/reverse/reapply without credential backfill: PASS")

# C4 operation budgets are additive and do not mutate source or dataset rows.
c4_target = ("integration", "0004_sourceoperationbudget")
executor = MigrationExecutor(connection)
executor.migrate([new_target, c4_target])
c4_apps = executor.loader.project_state([new_target, c4_target]).apps
assert c4_apps.get_model("integration", "SourceOperationBudget").objects.count() == 0
assert c4_apps.get_model("integration", "DataSource").objects.get(pk=source_id).workspace_id == 7
assert c4_apps.get_model("database", "Database").objects.get(pk=legacy.pk).source_id == source_id

executor = MigrationExecutor(connection)
executor.migrate([new_target, c3_target])
executor = MigrationExecutor(connection)
executor.migrate([new_target, c4_target])
reapplied_c4 = executor.loader.project_state([new_target, c4_target]).apps
assert reapplied_c4.get_model("integration", "SourceOperationBudget").objects.count() == 0
assert reapplied_c4.get_model("database", "Database").objects.get(pk=legacy.pk).source_id == source_id
print("Foundation-C C4 migration forward/reverse/reapply: PASS")
