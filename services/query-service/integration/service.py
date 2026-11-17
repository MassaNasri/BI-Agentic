"""The only application write interface for Integration source definitions."""

from .metadata import safe_connection_metadata
from .models import DataSource, CdcPipeline
from .cdc_lifecycle import record_command
from bi_platform_shared.db_ownership import integration_atomic
import uuid


def selected_tables(value):
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("Select no more than 20 tables.")
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Invalid table selection.")
        name = str(item.get("name") or "").strip()
        schema = str(item.get("schema") or "").strip()
        if not name or len(name) > 255 or len(schema) > 255:
            raise ValueError("Invalid table selection.")
        key = (schema, name)
        if key in seen:
            raise ValueError("Duplicate table selections are not allowed.")
        seen.add(key)
        result.append({"schema": schema or None, "name": name})
    return result


def create_source(*, workspace_id, actor_id, name, engine, configuration, tables, strict_metadata=False):
    name = str(name or "").strip()
    engine = str(engine or "").strip().lower()
    if not name or len(name) > 255 or not engine or len(engine) > 32:
        raise ValueError("A valid source name and engine are required.")
    return DataSource.objects.create(
        workspace_id=workspace_id, created_by=actor_id, name=name,
        engine=engine, connection_metadata=safe_connection_metadata(configuration, strict=strict_metadata),
        selected_tables=selected_tables(tables),
    )


def owned_source(workspace_id, source_id, *, require_active=False):
    try:
        source_id = uuid.UUID(str(source_id))
    except (TypeError, ValueError):
        return None
    source = DataSource.objects.filter(pk=source_id, workspace_id=workspace_id).first()
    if source is None or (require_active and source.state != DataSource.ACTIVE):
        return None
    return source


def record_selection(source, tables):
    source.selected_tables = selected_tables(tables)
    source.save(update_fields=["selected_tables", "updated_at"])


@integration_atomic
def update_source(source, changes, *, actor_id):
    source = DataSource.objects.select_for_update().get(pk=source.pk)
    if source.state == DataSource.RETIRED:
        raise ValueError("A retired source cannot be changed.")
    allowed = {"name", "selected_tables", "state"}
    if set(changes) - allowed:
        raise ValueError("Unknown source field.")
    name = source.name
    metadata = source.connection_metadata
    tables = source.selected_tables
    state = source.state
    if "name" in changes:
        name = str(changes["name"] or "").strip()
        if not name or len(name) > 255:
            raise ValueError("A valid source name is required.")
    if "selected_tables" in changes:
        tables = selected_tables(changes["selected_tables"])
        selected = {(item["schema"] or "public", item["name"]) for item in tables}
        if any((p.table_schema, p.table_name) not in selected for p in source.cdc_pipelines.all()):
            raise ValueError("CDC_TABLE_BOUND")
    if "state" in changes:
        state = changes["state"]
        if state not in (DataSource.ACTIVE, DataSource.DISABLED):
            raise ValueError("State must be active or disabled.")
    source.name = name
    source.connection_metadata = metadata
    source.selected_tables = tables
    source.state = state
    source.save()
    if state == DataSource.DISABLED:
        for pipeline in CdcPipeline.objects.select_for_update().filter(source=source).iterator():
            prior_desired, prior_observed = pipeline.desired_state, pipeline.observed_state
            if pipeline.desired_state != "STOPPED":
                pipeline.desired_state = "STOPPED"
                if pipeline.observed_state != "RESEED_REQUIRED":
                    pipeline.observed_state = "STOPPING"
                pipeline.save(update_fields=["desired_state", "observed_state", "updated_at"])
                record_command(pipeline, actor_id, "source_disabled", prior_desired, prior_observed, "CDC_ACCEPTED")
    return source


@integration_atomic
def retire_source(source, *, actor_id):
    source = DataSource.objects.select_for_update().get(pk=source.pk)
    source.state = DataSource.RETIRED
    source.save(update_fields=["state", "updated_at"])
    for pipeline in CdcPipeline.objects.select_for_update().filter(source=source).iterator():
        prior_desired, prior_observed = pipeline.desired_state, pipeline.observed_state
        if pipeline.desired_state != "STOPPED":
            pipeline.desired_state = "STOPPED"
            if pipeline.observed_state != "RESEED_REQUIRED":
                pipeline.observed_state = "STOPPING"
            pipeline.save(update_fields=["desired_state", "observed_state", "updated_at"])
            record_command(pipeline, actor_id, "source_retired", prior_desired, prior_observed, "CDC_ACCEPTED")
    return source
