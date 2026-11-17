"""Forward/reverse/reapply only in a separately named disposable PostgreSQL DB."""
import os
from pathlib import Path
import runpy

if os.getenv('BIAVORA_MIGRATION_DISPOSABLE') != '1' or not os.getenv('DB_NAME', '').startswith('foundation_d_migration'):
    raise SystemExit('Requires an explicitly disposable foundation_d_migration database.')

runpy.run_path(str(Path(__file__).with_name('verify_foundation_c_migration.py')))
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

old = ('integration', '0004_sourceoperationbudget')
new = ('integration', '0005_cdcpipeline_cdcaudit_and_more')
executor = MigrationExecutor(connection)
executor.migrate([new])
apps = executor.loader.project_state([new]).apps
assert apps.get_model('integration', 'CdcPipeline').objects.count() == 0
assert apps.get_model('integration', 'CdcAudit').objects.count() == 0
source = apps.get_model('integration', 'DataSource').objects.get()
source_id = source.pk
executor = MigrationExecutor(connection)
executor.migrate([old])
executor = MigrationExecutor(connection)
executor.migrate([new])
apps = executor.loader.project_state([new]).apps
assert apps.get_model('integration', 'DataSource').objects.get().pk == source_id
assert apps.get_model('integration', 'CdcPipeline').objects.count() == 0
assert apps.get_model('integration', 'CdcAudit').objects.count() == 0
print('Foundation-D 0005 forward/reverse/reapply: PASS; legacy source retained; no fabricated CDC backfill')

# D1 adds bounded desired state and scoped command metadata without rewriting
# the already established 0005 history.
d1 = ('integration', '0006_cdcaudit_dataset_id_cdcaudit_new_desired_state_and_more')
executor = MigrationExecutor(connection)
executor.migrate([d1])
apps = executor.loader.project_state([d1]).apps
Pipeline = apps.get_model('integration', 'CdcPipeline')
Audit = apps.get_model('integration', 'CdcAudit')
source = apps.get_model('integration', 'DataSource').objects.get(pk=source_id)
pipeline = Pipeline.objects.create(source=source, workspace_id=7, dataset_id=12345,
                                   table_schema='public', table_name='orders')
Audit.objects.create(pipeline=pipeline, actor_id=11, action='enable',
                     workspace_id=7, source_id=source_id, dataset_id=12345,
                     previous_desired_state='STREAMING', new_desired_state='STREAMING',
                     result_code='CDC_ACCEPTED')
from django.db import IntegrityError, transaction
try:
    with transaction.atomic():
        Pipeline.objects.create(source=source, workspace_id=7, dataset_id=12346,
                                table_schema='public', table_name='other',
                                desired_state='SNAPSHOTTING')
except IntegrityError:
    pass
else:
    raise AssertionError('The D1 desired-state constraint was not enforced.')

executor = MigrationExecutor(connection)
executor.migrate([new])
apps = executor.loader.project_state([new]).apps
assert apps.get_model('integration', 'CdcPipeline').objects.get(pk=pipeline.pk).dataset_id == 12345
assert apps.get_model('integration', 'CdcAudit').objects.filter(pipeline_id=pipeline.pk).count() == 1
executor = MigrationExecutor(connection)
executor.migrate([d1])
apps = executor.loader.project_state([d1]).apps
assert apps.get_model('integration', 'CdcPipeline').objects.get(pk=pipeline.pk).desired_state == 'STREAMING'
assert apps.get_model('integration', 'CdcAudit').objects.filter(pipeline_id=pipeline.pk).count() == 1
assert apps.get_model('integration', 'DataSource').objects.get(pk=source_id).workspace_id == 7
print('Foundation-D D1 0006 forward/reverse/reapply: PASS; CDC and owner rows retained; desired constraint enforced')

d5 = ('integration', '0007_cdc_generation')
executor = MigrationExecutor(connection)
executor.migrate([d5])
apps = executor.loader.project_state([d5]).apps
Generation = apps.get_model('integration', 'CdcGeneration')
lineage = Generation.objects.get(pipeline_id=pipeline.pk, number=1)
assert (lineage.workspace_id, lineage.source_id, lineage.dataset_id,
        lineage.table_schema, lineage.table_name) == (7, source_id, 12345, 'public', 'orders')
assert apps.get_model('integration', 'CdcPipeline').objects.get(pk=pipeline.pk).generation == 1
executor = MigrationExecutor(connection)
executor.migrate([d1])
apps = executor.loader.project_state([d1]).apps
assert apps.get_model('integration', 'CdcPipeline').objects.get(pk=pipeline.pk).dataset_id == 12345
executor = MigrationExecutor(connection)
executor.migrate([d5])
apps = executor.loader.project_state([d5]).apps
assert apps.get_model('integration', 'CdcGeneration').objects.filter(
    pipeline_id=pipeline.pk, number=1).count() == 1
print('Foundation-D D5 0007 forward/reverse/reapply: PASS; existing lineage backfilled once')

lease = ('integration', '0008_cdc_controller_lease')
executor = MigrationExecutor(connection)
executor.migrate([lease])
apps = executor.loader.project_state([lease]).apps
current = apps.get_model('integration', 'CdcPipeline').objects.get(pk=pipeline.pk)
assert current.controller_fence == 0 and current.controller_lease_owner is None
executor = MigrationExecutor(connection)
executor.migrate([d5])
executor = MigrationExecutor(connection)
executor.migrate([lease])
apps = executor.loader.project_state([lease]).apps
assert apps.get_model('integration', 'CdcPipeline').objects.get(pk=pipeline.pk).dataset_id == 12345
print('Foundation-D D5 0008 forward/reverse/reapply: PASS; lease starts unclaimed')

signal = ('integration', '0009_cdc_snapshot_signal')
executor = MigrationExecutor(connection)
executor.migrate([signal])
apps = executor.loader.project_state([signal]).apps
assert apps.get_model('integration', 'CdcPipeline').objects.get(pk=pipeline.pk).snapshot_signal == {}
assert apps.get_model('integration', 'CdcGeneration').objects.get(
    pipeline_id=pipeline.pk, number=1).snapshot_signal == {}
executor = MigrationExecutor(connection)
executor.migrate([lease])
executor = MigrationExecutor(connection)
executor.migrate([signal])
apps = executor.loader.project_state([signal]).apps
assert apps.get_model('integration', 'CdcGeneration').objects.filter(
    pipeline_id=pipeline.pk, number=1).count() == 1
print('Foundation-D D5 0009 forward/reverse/reapply: PASS; snapshot signal starts empty')

cutover = ('integration', '0010_cdc_candidate_cutover')
executor = MigrationExecutor(connection)
executor.migrate([cutover])
apps = executor.loader.project_state([cutover]).apps
Generation = apps.get_model('integration', 'CdcGeneration')
current = Generation.objects.get(pipeline_id=pipeline.pk, number=1)
assert current.cutover_phase == 'NONE' and current.validation_certificate == {}
assert current.candidate_ready_at is None and current.query_bound_at is None
candidate_fields = dict(pipeline_id=pipeline.pk, workspace_id=7, source_id=source_id,
                        dataset_id=12345, table_schema='public', table_name='orders')
Generation.objects.create(number=2, state='CANDIDATE', **candidate_fields)
try:
    with transaction.atomic():
        Generation.objects.create(number=3, state='CANDIDATE', **candidate_fields)
except IntegrityError:
    pass
else:
    raise AssertionError('A second candidate generation was accepted')
try:
    with transaction.atomic():
        Generation.objects.create(number=3, state='ACTIVE', **candidate_fields)
except IntegrityError:
    pass
else:
    raise AssertionError('A second active generation was accepted')
Generation.objects.filter(pipeline_id=pipeline.pk, number=2).delete()
executor = MigrationExecutor(connection)
executor.migrate([signal])
executor = MigrationExecutor(connection)
executor.migrate([cutover])
apps = executor.loader.project_state([cutover]).apps
assert apps.get_model('integration', 'CdcGeneration').objects.filter(
    pipeline_id=pipeline.pk, number=1).count() == 1
print('Foundation-D D5 0010 forward/reverse/reapply: PASS; cutover defaults, single-active/candidate constraints and generation retained')

reconciliation = ('integration', '0011_cdc_capture_and_reconciliation_attempt')
executor = MigrationExecutor(connection)
executor.migrate([reconciliation])
apps = executor.loader.project_state([reconciliation]).apps
assert apps.get_model('integration', 'CdcGeneration').objects.get(
    pipeline_id=pipeline.pk, number=1).reconciliation_attempt == {}
current_pipeline = apps.get_model('integration', 'CdcPipeline').objects.get(pk=pipeline.pk)
assert current_pipeline.capture_slot_seen is False and current_pipeline.capture_ready is False
executor = MigrationExecutor(connection)
executor.migrate([cutover])
executor = MigrationExecutor(connection)
executor.migrate([reconciliation])
apps = executor.loader.project_state([reconciliation]).apps
assert apps.get_model('integration', 'CdcGeneration').objects.filter(
    pipeline_id=pipeline.pk, number=1).count() == 1
print('Foundation-D D5 0011 forward/reverse/reapply: PASS; capture and reconciliation defaults retained')

dataset_old = ('database', '0006_dataset_source')
dataset_new = ('database', '0007_database_cdc_generation')
executor = MigrationExecutor(connection)
executor.migrate([dataset_old, reconciliation])
apps = executor.loader.project_state([dataset_old, reconciliation]).apps
LegacyDataset = apps.get_model('database', 'Database')
legacy_dataset_id = source.legacy_dataset_id
LegacyDataset.objects.filter(pk=legacy_dataset_id).update(source_kind='cdc', etl_status='completed')
executor = MigrationExecutor(connection)
executor.migrate([dataset_new, reconciliation])
apps = executor.loader.project_state([dataset_new, reconciliation]).apps
assert apps.get_model('database', 'Database').objects.get(pk=legacy_dataset_id).cdc_generation == 1
executor = MigrationExecutor(connection)
executor.migrate([dataset_old, reconciliation])
executor = MigrationExecutor(connection)
executor.migrate([dataset_new, reconciliation])
apps = executor.loader.project_state([dataset_new, reconciliation]).apps
assert apps.get_model('database', 'Database').objects.get(pk=legacy_dataset_id).cdc_generation == 1
print('Foundation-D D5 Query Dataset 0007 forward/reverse/reapply: PASS; generation-1 backfill retained')
