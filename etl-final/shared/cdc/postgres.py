"""Read-only CDC preflight and bounded reconciliation. Never grants privileges."""
import os
import json
from decimal import Decimal
import psycopg2
from psycopg2 import sql
from psycopg2.extras import register_default_json, register_default_jsonb
from bi_platform_shared.cdc_contract import CdcError
from shared.security.transport import get_transport
from .schema import inspect_schema


def connect(configuration, *, read_only=True):
    # Java/JDBC reconnect DNS pinning is not yet certified. Preserve C's hard
    # production transport gate instead of silently weakening it for Connect.
    if os.getenv("APP_ENV") == "production":
        raise CdcError("CDC_TRANSPORT_UNCERTIFIED")
    target = get_transport("direct_secure_internet").before_connect(configuration, "postgres")
    connection = psycopg2.connect(host=target.hostname, hostaddr=target.address, port=target.port,
        dbname=configuration["database"], user=configuration["username"], password=configuration["password"],
        sslmode=configuration.get("sslmode", "verify-full"), connect_timeout=5,
        options="-c statement_timeout=5000 -c default_transaction_read_only="
                + ("on" if read_only else "off"))
    # psycopg2's default JSON decoder converts fractional numbers to binary
    # float. Source reconciliation must preserve exact JSON numeric text.
    loads = lambda raw: json.loads(raw, parse_float=Decimal)
    register_default_json(connection, loads=loads)
    register_default_jsonb(connection, loads=loads)
    return connection


def reconciliation_marker(configuration):
    """Emit a source-database WAL marker without touching customer tables."""
    connection = connect(configuration, read_only=False)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_logical_emit_message(true, 'biavora_reconcile', 'watermark')::text")
            marker = cursor.fetchone()[0]
        connection.commit()
        return marker
    finally:
        connection.close()


def slot_health(connection, scope, *, existing=False):
    """Read the physical capture boundary independently of Connect status."""
    with connection.cursor() as cur:
        cur.execute("SELECT slot_name, active, restart_lsn::text, pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)::bigint, wal_status, slot_type, plugin, database, temporary, confirmed_flush_lsn::text, active_pid FROM pg_replication_slots WHERE slot_name=%s", ("b_" + scope.token,))
        found = cur.fetchone()
    if found and found[5:9] != ('logical', 'pgoutput', connection.info.dbname, False):
        raise CdcError("CDC_SLOT_INVALID")
    if found and found[4] in {'unreserved', 'lost'}:
        raise CdcError("CDC_SLOT_LOST")
    # A freshly created logical slot can be visible before both positions are
    # initialized. Only a slot previously observed as usable is continuity.
    initialized = bool(found and found[2] is not None and found[9] is not None)
    if found and not initialized and existing:
        raise CdcError("CDC_SLOT_INVALID")
    if existing and not found:
        raise CdcError("CDC_SLOT_LOST")
    return ({"slot_active": bool(initialized and found[1]), "retained_wal_bytes": int(found[3] or 0) if found else 0,
             "wal_warning": bool(found and int(found[3] or 0) > 268435456)},
            found[10] if found else None, bool(found))


def preflight(connection, scope, existing=False):
    slot, publication = "b_" + scope.token, "b_" + scope.publication_token
    with connection.cursor() as cur:
        cur.execute("SELECT current_setting('server_version_num')::int, current_setting('wal_level'), rolreplication, rolsuper FROM pg_roles WHERE rolname=current_user")
        version, wal, replication, superuser = cur.fetchone()
        if not 150000 <= version < 190000 or wal != "logical":
            raise CdcError("CDC_WAL_UNAVAILABLE")
        if not replication or superuser:
            raise CdcError("CDC_REPLICATION_ROLE_REQUIRED")
        cur.execute("SELECT has_table_privilege(current_user, %s, 'SELECT'), c.relreplident, c.relkind, c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname=%s",
                    (f'"{scope.schema}"."{scope.table}"', scope.schema, scope.table))
        row = cur.fetchone()
        if not row or not row[0] or row[1] != 'f':
            raise CdcError("CDC_REPLICA_IDENTITY_FULL_REQUIRED")
        if row[2] != 'r' or row[3]:
            raise CdcError("CDC_TABLE_UNSUPPORTED")
        cur.execute("SELECT pubinsert AND pubupdate AND pubdelete AND NOT puballtables FROM pg_publication WHERE pubname=%s", (publication,))
        if cur.fetchone() != (True,):
            raise CdcError("CDC_PUBLICATION_REQUIRED")
        cur.execute("SELECT schemaname, tablename FROM pg_publication_tables WHERE pubname=%s", (publication,))
        if cur.fetchall() != [(scope.schema, scope.table)]:
            raise CdcError("CDC_PUBLICATION_REQUIRED")
        health, _, slot_present = slot_health(connection, scope, existing=existing)
        cur.execute("SELECT current_setting('max_replication_slots')::int - (SELECT count(*) FROM pg_replication_slots), current_setting('max_wal_senders')::int - (SELECT count(*) FROM pg_stat_replication)")
        free_slots, free_senders = cur.fetchone()
        if (not slot_present and free_slots < 1) or (not health['slot_active'] and free_senders < 1):
            raise CdcError("CDC_REPLICATION_CAPACITY")
    columns, primary_key = inspect_schema(connection, scope.schema, scope.table)
    with connection.cursor() as cur:
        cur.execute("SELECT attnames, rowfilter FROM pg_publication_tables WHERE pubname=%s", (publication,))
        names, row_filter = cur.fetchone()
        if set(names) != {c['name'] for c in columns} or row_filter is not None:
            raise CdcError("CDC_PUBLICATION_FILTER_UNSUPPORTED")
    return columns, primary_key, health


def bounded_rows(connection, scope, primary_key, limit=10000):
    with connection.cursor() as cur:
        cur.execute(sql.SQL("SELECT * FROM {}.{} ORDER BY {} LIMIT %s").format(
            sql.Identifier(scope.schema), sql.Identifier(scope.table),
            sql.SQL(',').join(map(sql.Identifier, primary_key))), (limit + 1,))
        names = [c.name for c in cur.description]
        rows = [dict(zip(names, r)) for r in cur.fetchall()]
    if len(rows) > limit:
        raise CdcError("CDC_RECONCILIATION_LIMIT")
    return rows
