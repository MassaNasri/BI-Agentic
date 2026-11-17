"""Loader's CDC storage adapter: durable versions and tombstones, exact views."""
import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from bi_platform_shared.cdc_contract import identifier, CdcError, canonical
from .schema import clickhouse_type


class BatchConflict(CdcError):
    """A deterministic conflict at one input position; no batch rows were written."""

    def __init__(self, index):
        super().__init__('CDC_VERSION_CONFLICT')
        self.index = index


class CurrentStateStore:
    def __init__(self, client, database):
        self.client = client
        self.database = identifier(database)
        self._verified = set()

    def names(self, scope):
        return f'`{self.database}`.`cdc_{scope.token}_versions`', f'`{self.database}`.`cdc_{scope.token}_current`'

    def storage_state(self, scope):
        """Read-only existence check; a partial pair is never auto-recreated."""
        versions = f'cdc_{scope.token}_versions'
        current = f'cdc_{scope.token}_current'
        rows = list(self.client.query(
            'SELECT name, engine FROM system.tables WHERE database={database:String} '
            'AND name IN ({versions:String},{current:String})',
            parameters={'database': self.database, 'versions': versions,
                        'current': current}).named_results())
        if not rows:
            return 'MISSING'
        objects = {row['name']: row['engine'] for row in rows}
        if objects != {versions: 'MergeTree', current: 'View'}:
            return 'INVALID'
        return 'PRESENT'

    def prepare(self, scope, columns, primary_key):
        versions, view = self.names(scope)
        fields = []
        for c in columns:
            name = identifier(c['name'])
            typ = clickhouse_type(c['postgres_type'], c['nullable'])
            if typ != c['clickhouse_type']:
                raise CdcError("CDC_TYPE_UNSUPPORTED")
            fields.append(f'`{name}` {typ}')
        if not primary_key or len(set(primary_key)) != len(primary_key) or not set(primary_key) <= {c['name'] for c in columns}:
            raise CdcError("CDC_PRIMARY_KEY_REQUIRED")
        keys = ','.join(f'`{identifier(k)}`' for k in primary_key)
        self.client.command(f"CREATE TABLE IF NOT EXISTS {versions} ({','.join(fields)}, _cdc_version UInt128, _cdc_deleted UInt8, _cdc_event_id FixedString(64)) ENGINE=MergeTree ORDER BY ({keys},_cdc_version)")
        for index, field in enumerate(fields):
            position = (' FIRST' if index == 0 else
                        f' AFTER `{identifier(columns[index - 1]["name"])}`')
            self.client.command(
                f"ALTER TABLE {versions} ADD COLUMN IF NOT EXISTS {field}{position}")
        selected = ','.join(f'`{identifier(c["name"])}`' for c in columns)
        # Retain every distinct version. Select the newest before filtering its
        # tombstone; background merges cannot erase identity/conflict history.
        self.client.command(
            f"CREATE OR REPLACE VIEW {view} AS SELECT {selected} FROM ("
            f"SELECT {selected},_cdc_deleted,row_number() OVER (PARTITION BY {keys} "
            f"ORDER BY _cdc_version DESC) AS _cdc_rank FROM {versions}) "
            "WHERE _cdc_rank=1 AND _cdc_deleted=0")
        self._verified.discard(scope.token)

    def _verify_storage(self, scope, primary_key):
        if scope.token in self._verified:
            return
        versions, _ = self.names(scope)
        name = f'cdc_{scope.token}_versions'
        rows = list(self.client.query(
            'SELECT engine, sorting_key FROM system.tables WHERE database = {database:String} '
            'AND name = {name:String}',
            parameters={'database': self.database, 'name': name}).named_results())
        expected_key = ','.join([*primary_key, '_cdc_version'])
        if (len(rows) != 1 or rows[0]['engine'] != 'MergeTree'
                or rows[0]['sorting_key'].replace('`', '').replace(' ', '').replace('(', '').replace(')', '') != expected_key):
            raise CdcError('CDC_STORAGE_INCOMPATIBLE')
        self._verified.add(scope.token)

    @staticmethod
    def _stored_value(value, column):
        if value is None:
            return None
        pg_type = column['postgres_type']
        if pg_type.startswith('numeric('):
            scale = int(pg_type.rsplit(',', 1)[1][:-1])
            return format(Decimal(str(value)), f'.{scale}f')
        if pg_type == 'uuid':
            return str(value).lower()
        if pg_type == 'date':
            return value.isoformat() if isinstance(value, date) else str(value)
        if pg_type.startswith('timestamp'):
            if isinstance(value, datetime):
                if value.tzinfo is not None:
                    value = value.astimezone(timezone.utc).replace(tzinfo=None)
                return value.isoformat(sep=' ', timespec='microseconds')
            return str(value).replace('T', ' ')
        return value

    def apply(self, scope, event, columns, primary_key):
        versions, _ = self.names(scope)
        catalog = {column['name']: column for column in columns}
        if (not primary_key or len(set(primary_key)) != len(primary_key)
                or set(event['primary_key']) != set(primary_key) or set(event['row']) != set(catalog)):
            raise CdcError('CDC_SCHEMA_INCOMPATIBLE')
        self._verify_storage(scope, primary_key)
        predicates = []
        parameters = {'version': str(event['version'])}
        for index, name in enumerate(primary_key):
            identifier(name)
            pg_type = catalog[name]['clickhouse_type']
            if pg_type.startswith('Nullable('):
                raise CdcError('CDC_PRIMARY_KEY_REQUIRED')
            predicates.append(f'`{name}` = CAST({{key_{index}:String}} AS {pg_type})')
            value = event['row'][name]
            parameters[f'key_{index}'] = '1' if value is True else '0' if value is False else str(value)
        selected = ','.join(f'`{identifier(column["name"])}`' for column in columns)
        query = (f'SELECT DISTINCT _cdc_event_id, _cdc_deleted, {selected} FROM {versions} '
                 f'WHERE {" AND ".join(predicates)} AND _cdc_version = toUInt128({{version:String}}) LIMIT 2')
        existing = list(self.client.query(query, parameters=parameters,
                                          settings={'max_execution_time': 10, 'max_rows_to_read': 1000000}).named_results())
        expected_row = event['row']
        for stored in existing:
            stored_id = stored['_cdc_event_id']
            if isinstance(stored_id, bytes):
                stored_id = stored_id.decode('ascii')
            stored_row = {name: self._stored_value(stored[name], column) for name, column in catalog.items()}
            if (stored_id != event['event_id'] or stored['_cdc_deleted'] != int(event['operation'] == 'DELETE')
                    or stored_row != expected_row):
                raise CdcError('CDC_VERSION_CONFLICT')
        if existing:
            return False
        row = {**event['row'], '_cdc_version': event['version'],
               '_cdc_deleted': int(event['operation'] == 'DELETE'), '_cdc_event_id': event['event_id']}
        # JSONEachRow retains decimal strings and UInt128 without float loss.
        self.client.raw_insert(versions, insert_block=json.dumps(row, allow_nan=False).encode(), fmt='JSONEachRow')
        return True

    def apply_batch(self, scope, events, columns, primary_key):
        """Check all identities before one bounded insert; replay fills any missing rows."""
        if not events or len(events) > 100:
            raise CdcError('CDC_BATCH_INVALID')
        versions, _ = self.names(scope)
        catalog = {column['name']: column for column in columns}
        if not primary_key or len(set(primary_key)) != len(primary_key):
            raise CdcError('CDC_SCHEMA_INCOMPATIBLE')
        for event in events:
            if (set(event['primary_key']) != set(primary_key)
                    or set(event['row']) != set(catalog)):
                raise CdcError('CDC_SCHEMA_INCOMPATIBLE')
        self._verify_storage(scope, primary_key)

        def identity(row, version):
            return canonical({name: row[name] for name in primary_key}), str(version)

        unique = {}
        for event in events:
            unique.setdefault(identity(event['row'], event['version']), event)
        predicates, parameters = [], {}
        for index, event in enumerate(unique.values()):
            parts = []
            for key_index, name in enumerate(primary_key):
                identifier(name)
                typ = catalog[name]['clickhouse_type']
                if typ.startswith('Nullable('):
                    raise CdcError('CDC_PRIMARY_KEY_REQUIRED')
                parameter = f'key_{index}_{key_index}'
                parts.append(f'`{name}` = CAST({{{parameter}:String}} AS {typ})')
                value = event['row'][name]
                parameters[parameter] = '1' if value is True else '0' if value is False else str(value)
            parameter = f'version_{index}'
            parts.append(f'_cdc_version = toUInt128({{{parameter}:String}})')
            parameters[parameter] = str(event['version'])
            predicates.append('(' + ' AND '.join(parts) + ')')
        selected = ','.join(f'`{identifier(column["name"])}`' for column in columns)
        query = (f'SELECT DISTINCT _cdc_event_id, _cdc_deleted, _cdc_version, {selected} '
                 f'FROM {versions} WHERE {" OR ".join(predicates)} LIMIT 201')
        existing_rows = list(self.client.query(
            query, parameters=parameters,
            settings={'max_execution_time': 10, 'max_rows_to_read': 1000000}).named_results())
        if len(existing_rows) > 200:
            raise CdcError('CDC_VERSION_CONFLICT')
        existing = {}
        for stored in existing_rows:
            row = {name: self._stored_value(stored[name], column)
                   for name, column in catalog.items()}
            existing.setdefault(identity(row, stored['_cdc_version']), []).append((stored, row))

        seen = {}
        to_insert = []
        for index, event in enumerate(events):
            key = identity(event['row'], event['version'])
            candidates = existing.get(key, [])
            if key in seen:
                candidates.append(seen[key])
            for stored, row in candidates:
                stored_id = stored['_cdc_event_id']
                if isinstance(stored_id, bytes):
                    stored_id = stored_id.decode('ascii')
                if (stored_id != event['event_id']
                        or stored['_cdc_deleted'] != int(event['operation'] == 'DELETE')
                        or row != event['row']):
                    raise BatchConflict(index)
            if candidates:
                continue
            stored = {'_cdc_event_id': event['event_id'],
                      '_cdc_deleted': int(event['operation'] == 'DELETE')}
            seen[key] = (stored, event['row'])
            to_insert.append({**event['row'], '_cdc_version': event['version'],
                              '_cdc_deleted': stored['_cdc_deleted'],
                              '_cdc_event_id': event['event_id']})
        if to_insert:
            # One JSONEachRow insert. After an uncertain response, replay checks
            # each key/version and inserts only identities still absent.
            block = '\n'.join(json.dumps(row, allow_nan=False) for row in to_insert).encode()
            self.client.raw_insert(versions, insert_block=block, fmt='JSONEachRow')
        return len(to_insert)

    def rows(self, scope, primary_key, limit=10000):
        _, view = self.names(scope)
        keys = ','.join(f'`{identifier(k)}`' for k in primary_key)
        result = self.client.query(f"SELECT * FROM {view} ORDER BY {keys} LIMIT {int(limit)+1}", settings={"max_execution_time": 5, "max_rows_to_read": 1000000})
        rows = list(result.named_results())
        if len(rows) > limit:
            raise CdcError("CDC_RECONCILIATION_LIMIT")
        return rows


def store_from_env():
    import clickhouse_connect
    return CurrentStateStore(clickhouse_connect.get_client(
        host=os.environ['CLICKHOUSE_HOST'], port=int(os.getenv('CLICKHOUSE_HTTP_PORT', '8123')),
        username=os.environ['CLICKHOUSE_USER'], password=os.environ['CLICKHOUSE_PASSWORD'],
        connect_timeout=5, send_receive_timeout=10), os.getenv('CLICKHOUSE_DATABASE', 'etl'))
