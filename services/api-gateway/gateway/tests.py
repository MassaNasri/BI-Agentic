from django.http import JsonResponse
from django.test import RequestFactory, SimpleTestCase

from gateway.middleware import GatewayAuthenticationMiddleware


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
