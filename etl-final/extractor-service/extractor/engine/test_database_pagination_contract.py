import unittest
from unittest.mock import Mock
from unittest.mock import patch

from .database_extraction_strategy import DatabaseExtractionStrategy
from .extraction_strategy import ExtractionConfig, ExtractionError


class TestDatabasePaginationContract(unittest.TestCase):
    def setUp(self):
        self.strategy = DatabaseExtractionStrategy()

    def _mysql_connection(self, rows=None):
        connection = Mock()
        connection.__class__.__module__ = "pymysql.connections"
        cursor = Mock()
        cursor.fetchall.return_value = rows or []
        cursor.description = [("id",)] if rows else []
        connection.cursor.return_value = cursor
        return connection, cursor

    def test_requires_deterministic_ordering_when_no_pk_or_order_by_in_fail_mode(self):
        connection, _ = self._mysql_connection(rows=[])
        config = ExtractionConfig(
            source_id="users",
            source_type="database",
            connection_params={
                "connection": connection,
                "table": "users",
            },
            batch_size=100,
        )

        with patch.dict("os.environ", {"DB_NO_PK_MODE": "fail"}, clear=False):
            with self.assertRaises(ExtractionError):
                self.strategy.extract_batch(config, offset=0, limit=100)

    def test_warn_mode_allows_best_effort_when_no_pk_or_order_by(self):
        rows = [{"id": 1}]
        connection, cursor = self._mysql_connection(rows=rows)
        config = ExtractionConfig(
            source_id="users",
            source_type="database",
            connection_params={
                "connection": connection,
                "table": "users",
            },
            batch_size=100,
        )

        with patch.dict("os.environ", {"DB_NO_PK_MODE": "warn"}, clear=False):
            batch = self.strategy.extract_batch(config, offset=0, limit=100)

        query = cursor.execute.call_args[0][0]
        self.assertIn("LIMIT 100 OFFSET 0", query)
        self.assertNotIn("ORDER BY", query)
        self.assertTrue(batch.metadata["nondeterministic_paging"])
        self.assertEqual(batch.metadata["pagination_mode"], "best_effort_offset")

    def test_uses_keyset_pagination_when_pk_is_available(self):
        rows = [{"id": 11, "name": "alice"}, {"id": 12, "name": "bob"}]
        connection, cursor = self._mysql_connection(rows=rows)
        config = ExtractionConfig(
            source_id="users",
            source_type="database",
            connection_params={
                "connection": connection,
                "table": "users",
                "pk_column": "id",
                "last_pk": 10,
            },
            batch_size=2,
        )

        batch = self.strategy.extract_batch(config, offset=0, limit=2)
        executed_query = cursor.execute.call_args[0][0]
        executed_params = cursor.execute.call_args[0][1]

        self.assertIn("ORDER BY `id` ASC", executed_query)
        self.assertIn("WHERE `id` > %s", executed_query)
        self.assertNotIn("OFFSET", executed_query)
        self.assertEqual(executed_params, (10,))
        self.assertEqual(batch.metadata["pagination_mode"], "keyset")
        self.assertEqual(batch.metadata["next_last_pk"], 12)
