from types import SimpleNamespace

from django.test import TestCase
from rest_framework.test import APIClient


class SubscriptionApiSmokeTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_health_is_public(self):
        response = self.client.get("/subscription/health/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])

    def test_plan_catalog_rejects_anonymous_requests(self):
        response = self.client.get("/subscription/plans/")

        self.assertIn(response.status_code, (401, 403))

    def test_authenticated_plan_catalog_returns_current_catalog(self):
        principal = SimpleNamespace(is_authenticated=True, id=41, role="member")
        self.client.force_authenticate(user=principal)

        response = self.client.get("/subscription/plans/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {"success": True, "plans": []})
