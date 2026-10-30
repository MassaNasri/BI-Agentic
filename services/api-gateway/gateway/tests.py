from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase
from unittest.mock import Mock, patch

from gateway.middleware import GatewayAuthenticationMiddleware
from gateway.routing import resolve_target
from gateway.views import ProxyView


class GatewayAuthenticationMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = GatewayAuthenticationMiddleware(
            lambda request: JsonResponse({"status": "passed"})
        )

    def test_readiness_probe_does_not_require_user_credentials(self):
        response = self.middleware(self.factory.get("/ready/"))

        self.assertEqual(response.status_code, 200)

    def test_protected_route_still_requires_credentials(self):
        response = self.middleware(self.factory.get("/workspace/"))

        self.assertEqual(response.status_code, 401)


class GatewayFoundationCContractTests(SimpleTestCase):
    def test_internal_resolver_is_not_publicly_routed(self):
        self.assertIsNone(resolve_target("/internal/v1/source-credentials/resolve/"))
        self.assertIsNone(resolve_target("/workspace/internal/workspaces/create-manager/"))
        self.assertIsNone(resolve_target("/notification/events/"))
        self.assertIsNone(resolve_target("/notification/subscriptions/expiry-warnings/run/"))
        self.assertEqual(resolve_target("/database/sources/").service, "query-service")

    def test_proxy_hides_upstream_5xx_and_internal_fields(self):
        request = RequestFactory().get("/database/datasets/")
        for status_code, payload in (
            (500, {"error": "synthetic-upstream-secret"}),
            (200, {"data": {"clickhouse_table_name": "private_table"}}),
        ):
            upstream = Mock(status_code=status_code, content=b"synthetic-upstream-secret", headers={})
            upstream.json.return_value = payload
            with patch("gateway.views.requests.request", return_value=upstream):
                response = ProxyView.as_view()(request)
            self.assertEqual(response.status_code, 502)
            self.assertNotIn(b"synthetic-upstream-secret", response.content)
            self.assertNotIn(b"private_table", response.content)

    def test_public_report_metadata_is_filtered(self):
        upstream = Mock(status_code=200, content=b'{"physical_table_name":"private_table"}', headers={})
        upstream.json.return_value = {"physical_table_name": "private_table"}
        request = RequestFactory().get("/voice-reports/reports/")
        with patch("gateway.views.requests.request", return_value=upstream):
            response = ProxyView.as_view()(request)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn(b"private_table", response.content)

    def test_successful_sql_response_cannot_echo_physical_binding(self):
        physical = "w7_d31_orders_8a82"
        content = ('{"sql":"SELECT * FROM ' + physical + '"}').encode()
        upstream = Mock(status_code=200, content=content, headers={})
        upstream.json.return_value = {"sql": f"SELECT * FROM {physical}"}
        request = RequestFactory().post("/query/execute/")
        with patch("gateway.views.requests.request", return_value=upstream):
            response = ProxyView.as_view()(request)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn(physical.encode(), response.content)

    def test_non_json_and_internal_error_diagnostics_are_filtered(self):
        request = RequestFactory().get("/database/datasets/")
        for content, payload in (
            (b"Traceback (most recent call last): /app/private.py", None),
            (b'{"detail":"biavora_query.manager_databases"}',
             {"detail": "biavora_query.manager_databases"}),
        ):
            upstream = Mock(status_code=400, content=content, headers={})
            if payload is None:
                upstream.json.side_effect = ValueError()
            else:
                upstream.json.return_value = payload
            with patch("gateway.views.requests.request", return_value=upstream):
                response = ProxyView.as_view()(request)
            self.assertEqual(response.status_code, 502)
            self.assertNotIn(content, response.content)

    def test_internal_location_header_is_not_forwarded(self):
        upstream = Mock(
            status_code=302, content=b"", headers={"Location": "http://query-service:8006/private"},
        )
        request = RequestFactory().get("/database/datasets/")
        with patch("gateway.views.requests.request", return_value=upstream):
            response = ProxyView.as_view()(request)
        self.assertNotIn("Location", response)
