"""Query-owned, read-only candidate comparison through the authorized executor."""

import math
import time

from bi_platform_shared.cdc_contract import CdcError, identifier
from bi_platform_shared.cdc_reconciliation import chunk_digest
from query_api.resource_policy import QueryResourcePolicy, build_workspace_query_id
from query_api.services import SQLGuard, get_clickhouse_executor

from .cdc import _assert_current_view_ready, validate_live_dataset_binding
from .models import Database


MAX_RECONCILIATION_ROWS = 10_000
CHUNK_ROWS = 500


def candidate_digest(pipeline, candidate, scope):
    """Internal Query operation; no caller-selected physical name or SQL."""
    started = time.monotonic()
    if (candidate.pipeline_id != pipeline.pk or candidate.number != scope.generation
            or candidate.state != "CANDIDATE" or candidate.dataset_id != pipeline.dataset_id
            or candidate.workspace_id != pipeline.workspace_id
            or candidate.source_id != pipeline.source_id
            or scope.workspace_id != pipeline.workspace_id
            or scope.source_id != str(pipeline.source_id)
            or scope.pipeline_id != str(pipeline.pk)):
        raise CdcError("CDC_SCOPE_MISMATCH")
    dataset = Database.objects.filter(pk=pipeline.dataset_id).first()
    if dataset is None:
        raise CdcError("CDC_DATASET_BINDING_INVALID")
    validate_live_dataset_binding(dataset, pipeline.source, pipeline.table_schema, pipeline.table_name)
    _assert_current_view_ready(scope, dataset.clickhouse_database, pipeline.columns, pipeline.primary_key)
    view = "cdc_" + scope.token + "_current"
    database = dataset.clickhouse_database
    if not database or not all(identifier(name) for name in [database, *pipeline.primary_key]):
        raise CdcError("CDC_DATASET_BINDING_INVALID")
    allowed = {view}
    guard = SQLGuard(workspace_database=database, allowed_tables=allowed,
                     require_allowed_tables=True)
    policy = QueryResourcePolicy.from_environment()
    executor = get_clickhouse_executor()

    def execute(sql, page=1, size=CHUNK_ROWS):
        valid, _, clean = guard.validate_and_sanitize(sql)
        if not valid:
            raise CdcError("CDC_QUERY_RECONCILIATION_DENIED")
        result = executor.execute_query(clean, workspace_database=database,
                                        policy=policy, page=page, page_size=size,
                                        query_id=build_workspace_query_id(
                                            pipeline.workspace_id, f"cdc-reconcile-{scope.token}-{page}"))
        if not result.get("success"):
            raise CdcError("CDC_QUERY_RECONCILIATION_UNAVAILABLE")
        return result["rows"]

    table = f"`{database}`.`{view}`"
    count_rows = execute(f"SELECT count() AS n FROM {table}", size=1)
    if len(count_rows) != 1:
        raise CdcError("CDC_QUERY_RECONCILIATION_UNAVAILABLE")
    count = int(count_rows[0]["n"])
    limit = min(MAX_RECONCILIATION_ROWS, policy.max_rows)
    if count > limit:
        raise CdcError("CDC_RECONCILIATION_LIMIT")
    columns = pipeline.columns
    # Never shadow a primary-key name with a string cast. ClickHouse resolves
    # ORDER BY id to a SELECT alias named id, which sorts 1,10,100 before 2
    # and corrupts every bounded digest page despite equal row counts.
    business_names = {column["name"] for column in columns}
    aliases = []
    for index in range(len(columns)):
        alias = f"__cdc_value_{index}"
        while alias in business_names or alias in aliases:
            alias = "_" + alias
        aliases.append(alias)
    select = ", ".join(f"toString(`{identifier(column['name'])}`) AS `{alias}`"
                       for column, alias in zip(columns, aliases))
    order = ", ".join(f"`{identifier(name)}`" for name in pipeline.primary_key)
    sql = f"SELECT {select} FROM {table} ORDER BY {order}"
    chunks = []
    for page in range(1, math.ceil(count / CHUNK_ROWS) + 1):
        rows = execute(sql, page=page)
        expected = min(CHUNK_ROWS, count - (page - 1) * CHUNK_ROWS)
        if len(rows) != expected:
            raise CdcError("CDC_QUERY_RECONCILIATION_UNAVAILABLE")
        business = [{column["name"]: row[alias]
                     for column, alias in zip(columns, aliases)} for row in rows]
        chunks.append(chunk_digest(business, columns))
    return {"count": count, "chunks": chunks, "chunk_rows": CHUNK_ROWS,
            "duration_ms": int((time.monotonic() - started) * 1000)}
