"""Foundation-A endpoint tests backed by actual Query database records.

Run with::

    python manage.py test database.foundation_a_integration_tests \
        --settings=service_config.sqlite_test_settings
"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from database.models import Database
from query_api.views import QueryExecuteInternalView


@contextmanager
def _lease(*_args, **_kwargs):
    yield


def _principal(workspace_id: int):
    return SimpleNamespace(
        id=f"user-{workspace_id}",
        workspace_id=workspace_id,
        is_authenticated=True,
    )


class QuerySecurityEndpointIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dataset_a = Database.objects.create(
            manager=101,
            manager_email="a@example.test",
            workspace_id=1,
            filename="a.csv",
            file_size=1,
            file_path="/test/a.csv",
            clickhouse_database="workspace_a",
            clickhouse_table_name="table_a",
            etl_status="completed",
        )
        cls.dataset_b = Database.objects.create(
            manager=202,
            manager_email="b@example.test",
            workspace_id=2,
            filename="b.csv",
            file_size=1,
            file_path="/test/b.csv",
            clickhouse_database="workspace_b",
            clickhouse_table_name="table_b",
            etl_status="completed",
        )

    def _post(self, *, workspace_id: int, payload: dict, executor: Mock):
        request = APIRequestFactory().post("/query/execute/", payload, format="json")
        request.request_id = f"request-{workspace_id}"
        force_authenticate(request, user=_principal(workspace_id))
        with (
            patch(
                "query_api.application.query_execution.workspace_query_lease",
                _lease,
            ),
            patch(
                "query_api.application.query_execution.get_clickhouse_executor",
                return_value=executor,
            ),
        ):
            return QueryExecuteInternalView.as_view()(request)

    def test_actual_records_allow_each_workspace_own_dataset(self):
        executor = Mock()
        executor.execute_query.side_effect = lambda sql, **_kwargs: {
            "success": True,
            "rows": [{"source": "A" if "table_a" in sql else "B"}],
            "row_count": 1,
            "pagination": {"truncated": False},
        }

        response_a = self._post(
            workspace_id=1,
            payload={
                "dataset_id": self.dataset_a.pk,
                "sql": "SELECT * FROM table_a",
            },
            executor=executor,
        )
        response_b = self._post(
            workspace_id=2,
            payload={
                "dataset_id": self.dataset_b.pk,
                "sql": "SELECT * FROM table_b",
            },
            executor=executor,
        )

        self.assertEqual(response_a.status_code, 200)
        self.assertEqual(response_a.data["rows"], [{"source": "A"}])
        self.assertEqual(response_b.status_code, 200)
        self.assertEqual(response_b.data["rows"], [{"source": "B"}])
        self.assertEqual(executor.execute_query.call_count, 2)

    def test_actual_records_deny_cross_workspace_dataset_without_execution(self):
        executor = Mock()
        response = self._post(
            workspace_id=1,
            payload={
                "dataset_id": self.dataset_b.pk,
                "sql": "SELECT * FROM table_b",
            },
            executor=executor,
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["error_code"], "FORBIDDEN_DATASET")
        self.assertEqual(response.data["rows"], [])
        executor.execute_query.assert_not_called()

    def test_actual_records_deny_arbitrary_table_and_physical_override(self):
        executor = Mock()
        arbitrary = self._post(
            workspace_id=1,
            payload={
                "dataset_id": self.dataset_a.pk,
                "sql": "SELECT * FROM table_b",
            },
            executor=executor,
        )
        physical_override = self._post(
            workspace_id=1,
            payload={
                "dataset_id": self.dataset_a.pk,
                "workspace_database": "workspace_b",
                "sql": "SELECT * FROM table_a",
            },
            executor=executor,
        )

        self.assertEqual(arbitrary.status_code, 403)
        self.assertEqual(arbitrary.data["rows"], [])
        self.assertEqual(physical_override.status_code, 400)
        self.assertEqual(physical_override.data["rows"], [])
        executor.execute_query.assert_not_called()

