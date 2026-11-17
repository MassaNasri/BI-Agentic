"""Query publication requires an actual Loader-owned current View."""
import json
from unittest.mock import patch
from uuid import uuid4

from django.test import SimpleTestCase

from bi_platform_shared.cdc_contract import Scope
from database.cdc import CdcDatasetBindingError, _assert_current_view_ready


class Client:
    def __init__(self, scope, *, sorting='id, _cdc_version', view_engine='View', view_sql=None,
                 view_columns=None, success=True):
        token = scope.token
        self.versions = f'cdc_{token}_versions'
        self.current = f'cdc_{token}_current'
        self.sorting = sorting
        self.view_engine = view_engine
        self.view_sql = view_sql or (f'CREATE VIEW etl.{self.current} AS SELECT id, amount FROM '
                                     f'(SELECT id, amount, _cdc_deleted, row_number() OVER '
                                     f'(PARTITION BY id ORDER BY _cdc_version DESC) AS _cdc_rank '
                                     f'FROM etl.{self.versions}) WHERE _cdc_rank = 1 AND _cdc_deleted = 0')
        self.view_columns = view_columns
        self.success = success

    def execute_query(self, _query):
        rows = [{'name': self.versions, 'engine': 'MergeTree',
                 'sorting_key': self.sorting, 'create_table_query': ''},
                {'name': self.current, 'engine': self.view_engine,
                 'sorting_key': '', 'create_table_query': self.view_sql}]
        return {'success': self.success, 'data': '\n'.join(json.dumps(row) for row in rows)}

    def get_table_schema(self, _database, name):
        business = [{'name': 'id', 'type': 'Int32'},
                    {'name': 'amount', 'type': 'Decimal(20, 4)'}]
        technical = [{'name': '_cdc_version', 'type': 'UInt128'},
                     {'name': '_cdc_deleted', 'type': 'UInt8'},
                     {'name': '_cdc_event_id', 'type': 'FixedString(64)'}]
        return {'success': self.success,
                'schema': business + technical if name == self.versions else
                self.view_columns if self.view_columns is not None else business}


class CdcPhysicalPublicationTests(SimpleTestCase):
    def setUp(self):
        self.scope = Scope(11, str(uuid4()), str(uuid4()), 7, 'public', 'orders')
        self.columns = [{'name': 'id', 'clickhouse_type': 'Int32'},
                        {'name': 'amount', 'clickhouse_type': 'Decimal(20, 4)'}]

    def check(self, client):
        with patch('database.cdc.ClickHouseClient', return_value=client):
            _assert_current_view_ready(self.scope, 'etl', self.columns, ['id'])

    def test_exact_view_and_versions_are_ready(self):
        self.check(Client(self.scope))

    def test_wrong_object_or_key_or_delete_order_fails_closed(self):
        versions = f'cdc_{self.scope.token}_versions'
        current = f'cdc_{self.scope.token}_current'
        cases = [Client(self.scope, sorting='amount'),
                 Client(self.scope, view_engine='MergeTree'),
                 Client(self.scope, view_sql=f'CREATE VIEW etl.{current} AS SELECT id, amount FROM '
                                            f'etl.{versions} WHERE _cdc_deleted = 0'),
                 Client(self.scope, success=False)]
        for client in cases:
            with self.subTest(client=client):
                with self.assertRaisesRegex(CdcDatasetBindingError, 'CDC_PUBLICATION_NOT_READY'):
                    self.check(client)

    def test_technical_column_exposed_by_view_fails_closed(self):
        client = Client(self.scope, view_columns=[{'name': 'id', 'type': 'Int32'},
                                                  {'name': 'amount', 'type': 'Decimal(20, 4)'},
                                                  {'name': '_cdc_version', 'type': 'UInt128'}])
        with self.assertRaisesRegex(CdcDatasetBindingError, 'CDC_PUBLICATION_NOT_READY'):
            self.check(client)
