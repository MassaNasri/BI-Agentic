"""Query owns creation and publication of the analytical CDC binding."""
import json
import re
from uuid import NAMESPACE_URL, uuid5

from django.conf import settings
from django.db import models
from .models import Database
from .utils import ClickHouseClient, quote_clickhouse_string


class CdcDatasetBindingError(ValueError):
    """A Query dataset cannot safely serve the requested live source table."""


def _assert_current_view_ready(scope, database, columns, primary_key):
    """Read-only physical proof before Query publishes a CDC Dataset."""
    client = ClickHouseClient()
    versions = f'cdc_{scope.token}_versions'
    current = f'cdc_{scope.token}_current'
    expected = [(column['name'], column['clickhouse_type']) for column in columns]
    try:
        metadata = client.execute_query(
            'SELECT name, engine, sorting_key, create_table_query FROM system.tables '
            f'WHERE database = {quote_clickhouse_string(database)} '
            f'AND name IN ({quote_clickhouse_string(versions)}, {quote_clickhouse_string(current)}) '
            'FORMAT JSONEachRow')
        if not metadata['success']:
            raise CdcDatasetBindingError('CDC_PUBLICATION_NOT_READY')
        objects = {entry['name']: entry for entry in
                   (json.loads(line) for line in metadata['data'].splitlines() if line)}
        if (set(objects) != {versions, current}
                or objects[versions]['engine'] != 'MergeTree'
                or objects[current]['engine'] != 'View'):
            raise CdcDatasetBindingError('CDC_PUBLICATION_NOT_READY')
        sorting_key = objects[versions]['sorting_key'].replace('`', '').replace(' ', '').replace('(', '').replace(')', '')
        if sorting_key != ','.join([*primary_key, '_cdc_version']):
            raise CdcDatasetBindingError('CDC_PUBLICATION_NOT_READY')
        view_sql = ' '.join(objects[current]['create_table_query'].upper().replace('`', '').split())
        partition = ', '.join(primary_key).upper()
        view_tail = re.escape(f'FROM {database}.{versions}'.upper()) + (
            r'\) WHERE \(?_CDC_RANK = 1\)? AND \(?_CDC_DELETED = 0\)?$')
        if (f'ROW_NUMBER() OVER (PARTITION BY {partition} ORDER BY _CDC_VERSION DESC)' not in view_sql
                or not re.search(view_tail, view_sql)):
            raise CdcDatasetBindingError('CDC_PUBLICATION_NOT_READY')
        versions_schema = client.get_table_schema(database, versions)
        view_schema = client.get_table_schema(database, current)
        technical = [('_cdc_version', 'UInt128'), ('_cdc_deleted', 'UInt8'),
                     ('_cdc_event_id', 'FixedString(64)')]
        if (not versions_schema['success'] or not view_schema['success']
                or [(c['name'], c['type']) for c in versions_schema['schema']] != expected + technical
                or [(c['name'], c['type']) for c in view_schema['schema']] != expected):
            raise CdcDatasetBindingError('CDC_PUBLICATION_NOT_READY')
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, CdcDatasetBindingError):
            raise
        raise CdcDatasetBindingError('CDC_PUBLICATION_NOT_READY') from None


def binding_job_id(source, schema, table):
    # Unique per source/table for creation retries; a future reseed needs a
    # separately versioned generation rather than reusing this binding.
    return uuid5(NAMESPACE_URL, f"biavora:cdc:v1:{source.pk}:{schema}:{table}")


def validate_live_dataset_binding(dataset, source, schema, table):
    expected_name = f"Live: {schema}.{table}"
    selected = dataset.source_tables
    if (dataset.workspace_id != source.workspace_id or dataset.source_id != source.pk
            or dataset.source_kind != "cdc" or dataset.source_engine != "postgres"
            or dataset.filename != expected_name
            or not isinstance(selected, list)
            or (not selected and dataset.etl_status != "pending")
            or (selected and (len(selected) != 1 or not isinstance(selected[0], dict)
                              or selected[0].get("schema") != schema
                              or selected[0].get("name") != table))):
        raise CdcDatasetBindingError("CDC_DATASET_BINDING_INVALID")
    return dataset


def create_live_dataset(source, actor_id, schema, table):
    dataset, created = Database.objects.get_or_create(
        ingestion_job_id=binding_job_id(source, schema, table),
        defaults={
            "manager": actor_id, "workspace_id": source.workspace_id, "source_id": source.pk,
            "filename": f"Live: {schema}.{table}", "source_kind": "cdc", "source_engine": "postgres",
            "source_tables": [{"schema": schema, "name": table, "status": "pending"}],
            "file_size": 0, "file_path": "", "etl_status": "pending",
            "clickhouse_database": getattr(settings, "CLICKHOUSE_DATABASE", "etl"),
        },
    )
    validate_live_dataset_binding(dataset, source, schema, table)
    if not created and dataset.etl_status != "pending":
        raise CdcDatasetBindingError("CDC_DATASET_BINDING_INVALID")
    return dataset, created


def publish_live_dataset(pipeline, scope):
    # The physical name is derived by Query from a server-owned scope, not a
    # caller-supplied table name. The view contains no CDC technical columns.
    dataset = Database.objects.filter(pk=pipeline.dataset_id).first()
    if dataset is None:
        raise CdcDatasetBindingError("CDC_DATASET_BINDING_INVALID")
    validate_live_dataset_binding(dataset, pipeline.source, pipeline.table_schema, pipeline.table_name)
    if (dataset.etl_status not in {"pending", "completed"} or not pipeline.columns
            or not pipeline.primary_key or pipeline.desired_state != "STREAMING"
            or pipeline.observed_state != "STREAMING"
            or not (any(key.startswith("load:") for key in pipeline.checkpoints)
                    or pipeline.snapshot_signal.get("completed") is True)):
        raise CdcDatasetBindingError("CDC_PUBLICATION_NOT_READY")
    schema = {c["name"]: c["clickhouse_type"] for c in pipeline.columns}
    _assert_current_view_ready(scope, dataset.clickhouse_database, pipeline.columns, pipeline.primary_key)
    updated = Database.objects.filter(pk=pipeline.dataset_id, workspace_id=pipeline.workspace_id,
                            source_id=pipeline.source_id, source_kind="cdc",
                            etl_status__in=["pending", "completed"]).update(
        clickhouse_table_name=f"cdc_{scope.token}_current", cdc_generation=scope.generation, columns_schema=schema,
        column_count=len(schema), etl_status="completed",
        source_tables=[{"schema": pipeline.table_schema, "name": pipeline.table_name,
                        "destination_table": f"cdc_{scope.token}_current", "columns_schema": schema}],
    )
    if updated != 1:
        raise CdcDatasetBindingError("CDC_DATASET_BINDING_INVALID")


def candidate_binding_state(pipeline, old_scope, candidate_scope):
    """Query's stamped Dataset is the single analytical authority."""
    dataset = Database.objects.filter(pk=pipeline.dataset_id).first()
    if dataset is None:
        raise CdcDatasetBindingError("CDC_DATASET_BINDING_INVALID")
    validate_live_dataset_binding(dataset, pipeline.source, pipeline.table_schema, pipeline.table_name)
    if (dataset.workspace_id != pipeline.workspace_id or candidate_scope.workspace_id != pipeline.workspace_id
            or candidate_scope.source_id != str(pipeline.source_id)
            or candidate_scope.pipeline_id != str(pipeline.pk)
            or candidate_scope.dataset_id != pipeline.dataset_id
            or candidate_scope.generation <= old_scope.generation
            or dataset.etl_status not in {"pending", "completed"}):
        raise CdcDatasetBindingError("CDC_DATASET_BINDING_INVALID")
    if (dataset.etl_status == "pending" and old_scope.generation == 1
            and dataset.cdc_generation is None and not dataset.clickhouse_table_name):
        return "pending"
    if (dataset.etl_status == "completed" and dataset.cdc_generation == candidate_scope.generation
            and dataset.clickhouse_table_name == f"cdc_{candidate_scope.token}_current"):
        return "candidate"
    if ((dataset.cdc_generation == old_scope.generation
         or old_scope.generation == 1 and dataset.cdc_generation is None)
            and dataset.clickhouse_table_name == f"cdc_{old_scope.token}_current"):
        return "old"
    raise CdcDatasetBindingError("CDC_DATASET_BINDING_INVALID")


def cutover_candidate_binding(pipeline, old_scope, candidate_scope, columns, primary_key):
    """Query-owned compare-and-swap; repeatable after a lost response."""
    state = candidate_binding_state(pipeline, old_scope, candidate_scope)
    if state == "candidate":
        return False
    dataset = Database.objects.get(pk=pipeline.dataset_id)
    _assert_current_view_ready(candidate_scope, dataset.clickhouse_database, columns, primary_key)
    schema = {column["name"]: column["clickhouse_type"] for column in columns}
    old_filter = models.Q(cdc_generation=old_scope.generation,
                          etl_status="completed",
                          clickhouse_table_name=f"cdc_{old_scope.token}_current")
    if old_scope.generation == 1:
        old_filter |= models.Q(cdc_generation__isnull=True, etl_status="completed",
                               clickhouse_table_name=f"cdc_{old_scope.token}_current")
        old_filter |= models.Q(cdc_generation__isnull=True, etl_status="pending",
                               clickhouse_table_name__in=["", None])
    changed = Database.objects.filter(
        pk=dataset.pk, workspace_id=pipeline.workspace_id, source_id=pipeline.source_id,
        source_kind="cdc",
    ).filter(old_filter).update(
        cdc_generation=candidate_scope.generation,
        etl_status="completed",
        clickhouse_table_name=f"cdc_{candidate_scope.token}_current",
        columns_schema=schema, column_count=len(schema),
        source_tables=[{"schema": pipeline.table_schema, "name": pipeline.table_name,
                        "destination_table": f"cdc_{candidate_scope.token}_current", "columns_schema": schema}],
    )
    if changed != 1:
        raise CdcDatasetBindingError("CDC_DATASET_BINDING_INVALID")
    return True
