"""CDC datasets reject technical selectors before warehouse execution."""
from unittest.mock import patch

from django.test import SimpleTestCase

from query_api.application.query_execution import validate_sql_payload
from query_api.services.workspace_db_resolver import WorkspaceDatasetBinding


class CdcQueryGuardTests(SimpleTestCase):
    def setUp(self):
        self.binding = WorkspaceDatasetBinding(
            workspace_id=11, dataset_id=19, manager_id=11, clickhouse_db='etl',
            table_name='cdc_test_current', allowed_tables=frozenset({'cdc_test_current'}),
            etl_status='completed', source_kind='cdc')

    def validate(self, sql):
        with patch('query_api.application.query_execution.resolve_authorized_query_binding',
                   return_value=(self.binding, None, 200)):
            return validate_sql_payload({'sql': sql})

    def test_technical_column_fails_before_executor(self):
        result, status, _ = self.validate('SELECT _cdc_version FROM cdc_test_current')
        self.assertEqual(status, 403)
        self.assertEqual(result['error_code'], 'FORBIDDEN_DATASET')

    def test_string_literal_does_not_trigger_column_rule(self):
        result, status, _ = self.validate("SELECT '_cdc_version' AS label FROM cdc_test_current")
        self.assertEqual(status, 200)
        self.assertTrue(result['success'])
