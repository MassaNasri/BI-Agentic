"""Controller-owned source/transport proof for a candidate watermark.

The PostgreSQL repeatable-read snapshot fixes source truth. A flushed logical
slot plus Kafka stage-end offsets fixes the captured prefix. The Query service
computes destination digests through its own authorized candidate executor.
"""

import logging
import os
import time

from kafka import KafkaConsumer, TopicPartition
from psycopg2 import sql

from bi_platform_shared.cdc_contract import CdcError
from bi_platform_shared.cdc_reconciliation import chunk_digest, lsn_number
from . import postgres


MAX_ROWS = 10_000
CHUNK_ROWS = 500
WAIT_SECONDS = 60
log = logging.getLogger(__name__)


def source_chunks(connection, scope, columns, primary_key):
    kinds = {column["name"]: column["postgres_type"] for column in columns}
    if any(kinds[name] not in {"smallint", "integer", "bigint", "text"}
           and not kinds[name].startswith(("character varying", "character("))
           for name in primary_key):
        raise CdcError("CDC_RECONCILIATION_PK_UNSUPPORTED")
    order = []
    for name in primary_key:
        key = sql.Identifier(name)
        order.append(sql.SQL("{} COLLATE \"C\"").format(key) if kinds[name] == "text"
                     or kinds[name].startswith(("character varying", "character(")) else key)
    statement = sql.SQL("SELECT {} FROM {}.{} ORDER BY {} LIMIT %s").format(
        sql.SQL(",").join(sql.Identifier(column["name"]) for column in columns),
        sql.Identifier(scope.schema), sql.Identifier(scope.table), sql.SQL(",").join(order))
    chunks, count = [], 0
    with connection.cursor(name="biavora_reconciliation") as cursor:
        cursor.itersize = CHUNK_ROWS
        cursor.execute(statement, (MAX_ROWS + 1,))
        names = [column["name"] for column in columns]
        while True:
            records = cursor.fetchmany(CHUNK_ROWS)
            if not records:
                break
            count += len(records)
            if count > MAX_ROWS:
                raise CdcError("CDC_RECONCILIATION_LIMIT")
            chunks.append(chunk_digest((dict(zip(names, row)) for row in records), columns))
    return count, chunks


def _stage_ends(consumer, topic):
    partitions = consumer.partitions_for_topic(topic)
    if not partitions:
        return {"0": 0}
    selected = [TopicPartition(topic, number) for number in sorted(partitions)]
    begins = consumer.beginning_offsets(selected)
    ends = consumer.end_offsets(selected)
    if any(begins[partition] > 0 and begins[partition] > ends[partition] - 1
           for partition in selected):
        raise CdcError("CDC_KAFKA_RETENTION_LOST")
    return {str(partition.partition): int(ends[partition]) for partition in selected}


def _wait_stage(control, scope, stage, ends, deadline):
    while time.monotonic() < deadline:
        control.claim(scope)  # renew the same durable owner/fence while polling
        items = [item for item in control.pipelines()
                 if item["scope"] == scope.__dict__]
        if len(items) != 1 or items[0]["desired_state"] != "STREAMING":
            raise CdcError("CDC_STALE_CALLBACK")
        item = items[0]
        if item.get("error_code"):
            raise CdcError("CDC_CANDIDATE_NOT_READY")
        checkpoints = item["checkpoints"]
        if all(checkpoints.get(f"{stage}:{partition}", {}).get("offset", -1) >= end - 1
               for partition, end in ends.items()):
            return checkpoints
        time.sleep(1)
    raise CdcError("CDC_RECONCILIATION_WATERMARK_BEHIND")


def reconcile_candidate(connection, control, scope, columns, primary_key, configuration,
                        attempt):
    started = time.monotonic()
    attempt_id = attempt.get('id')
    if not attempt_id or attempt.get('generation') != scope.generation:
        raise CdcError('CDC_RECONCILIATION_ATTEMPT_MISSING')
    if attempt.get('state') != 'REQUESTED':
        # A process died after durable progress. A fresh operator request must
        # start a fresh source snapshot; no partial proof is reconstructed.
        control.reconciliation_progress(scope, attempt_id, 'FAILED',
                                        source_lsn=attempt.get('source_lsn', 0),
                                        stage_ends=attempt.get('stage_ends', {}),
                                        failure_code='CDC_RECONCILIATION_INTERRUPTED')
        return
    source_lsn = 0
    stage_ends = {}
    connection.rollback()
    connection.set_session(isolation_level="REPEATABLE READ", readonly=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_current_wal_lsn()::text")
            cursor.fetchone()  # establish the repeatable-read source snapshot
        control.reconciliation_progress(scope, attempt_id, 'SOURCE_SNAPSHOT_OPEN')
        # Isolated acceptance fixture: hold the established source snapshot at
        # a known boundary so a concurrent commit can be proved, not guessed.
        gate = os.getenv('CDC_D5_R4A_RECONCILE_GATE_SCOPE_TOKEN', '')
        if gate:
            if (os.getenv('APP_ENV') != 'test' or gate != scope.token
                    or scope.generation != 2 or configuration.get('host') != 'postgres'
                    or not configuration.get('database', '').startswith('source_d2_')):
                raise CdcError('CDC_RECONCILIATION_TEST_GATE_FORBIDDEN')
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(%s)',
                               (int(scope.token[:15], 16),))
        source_count, source = source_chunks(connection, scope, columns, primary_key)
        source_lsn = lsn_number(postgres.reconciliation_marker(configuration))
        control.reconciliation_progress(scope, attempt_id, 'WATERMARK_EMITTED', source_lsn)
        log.info("CDC_RECONCILIATION_MARKER scope=%s source_lsn=%s rows=%s",
                 scope.token, source_lsn, source_count)
        deadline = time.monotonic() + WAIT_SECONDS
        control.reconciliation_progress(scope, attempt_id, 'WAITING_CAPTURE', source_lsn)
        capture_lsn = 0
        while time.monotonic() < deadline:
            probe = postgres.connect(configuration)
            try:
                with probe.cursor() as cursor:
                    cursor.execute("SELECT confirmed_flush_lsn::text FROM pg_replication_slots "
                                   "WHERE slot_name=%s AND slot_type='logical' AND plugin='pgoutput'",
                                   ("b_" + scope.token,))
                    row = cursor.fetchone()
            finally:
                probe.close()
            if row is None or row[0] is None:
                raise CdcError("CDC_SLOT_LOST")
            capture_lsn = lsn_number(row[0])
            if capture_lsn >= source_lsn:
                break
            control.claim(scope)
            time.sleep(1)
        if capture_lsn < source_lsn:
            log.warning("CDC_RECONCILIATION_CAPTURE_BEHIND scope=%s source_lsn=%s capture_lsn=%s",
                        scope.token, source_lsn, capture_lsn)
            raise CdcError("CDC_CAPTURE_WATERMARK_BEHIND")
        log.info("CDC_RECONCILIATION_CAPTURE_READY scope=%s capture_lsn=%s",
                 scope.token, capture_lsn)
        control.reconciliation_progress(scope, attempt_id, 'WAITING_LOADER', source_lsn)
        consumer = KafkaConsumer(bootstrap_servers=__import__("os").environ["KAFKA_BOOTSTRAP_SERVERS"],
                                 enable_auto_commit=False, group_id=None,
                                 request_timeout_ms=15000)
        try:
            raw = _stage_ends(consumer, scope.raw_topic)
            _wait_stage(control, scope, "normalize", raw, deadline)
            normalized = _stage_ends(consumer, scope.topic("normalized"))
            _wait_stage(control, scope, "transform", normalized, deadline)
            transformed = _stage_ends(consumer, scope.topic("transformed"))
            checkpoints = _wait_stage(control, scope, "load", transformed, deadline)
            stage_ends = {"normalize": raw, "transform": normalized, "load": transformed}
        finally:
            consumer.close()
        control.reconciliation_progress(scope, attempt_id, 'COMPARING', source_lsn,
                                        stage_ends)
        control.verify(scope)
        query = control.candidate_digest(scope)
        if (not isinstance(query, dict) or type(query.get("count")) is not int
                or not isinstance(query.get("chunks"), list)
                or query.get("chunk_rows") != CHUNK_ROWS):
            raise CdcError("CDC_QUERY_RECONCILIATION_UNAVAILABLE")
        destination = query["chunks"]
        # A fresh source transaction detects commits after the initial source
        # snapshot. An ambiguous attempt fails durably and requires a new
        # request against a later source snapshot and WAL marker.
        current = postgres.connect(configuration)
        try:
            current.set_session(isolation_level="REPEATABLE READ", readonly=True)
            current_count, current_chunks = source_chunks(
                current, scope, columns, primary_key)
        finally:
            current.close()
        if current_count != source_count or current_chunks != source:
            raise CdcError('CDC_RECONCILIATION_SOURCE_MOVED')
        mismatch = [index for index in range(max(len(source), len(destination)))
                    if index >= len(source) or index >= len(destination)
                    or source[index] != destination[index]]
        proof = {"attempt_id": attempt_id, "source_lsn": source_lsn,
                 "capture_lsn": capture_lsn, "stage_ends": stage_ends,
                 "checkpoints": checkpoints, "source_count": source_count,
                 "query_count": query["count"], "chunk_count": len(source),
                 "mismatch_chunks": mismatch[:20],
                 "duration_ms": int((time.monotonic() - started) * 1000),
                 "query_duration_ms": int(query.get("duration_ms", 0))}
        control.verify(scope)
        return control.issue_watermark_certificate(scope, proof)
    except Exception as exc:
        code = exc.code if isinstance(exc, CdcError) else 'CDC_RECONCILIATION_FAILED'
        try:
            control.reconciliation_progress(scope, attempt_id, 'FAILED', source_lsn,
                                            stage_ends, code)
        except Exception:
            # A lost lease cannot write progress. The next owner sees the
            # nonterminal attempt and fails it before making a new proof.
            pass
        raise
    finally:
        connection.rollback()
