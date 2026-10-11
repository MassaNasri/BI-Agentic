from unittest.mock import patch

from django.test import override_settings
from rest_framework.test import APITestCase


@override_settings(NOTIFICATION_INTERNAL_API_KEY="notification-test-only-key")
class NotificationApiSmokeTests(APITestCase):
    def test_health_is_public(self):
        response = self.client.get("/notification/health/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])

    def test_event_endpoint_rejects_missing_service_key(self):
        response = self.client.post(
            "/notification/events/",
            {"event_type": "account_activation", "payload": {}},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    @override_settings(NOTIFICATION_INTERNAL_API_KEY="")
    def test_event_endpoint_fails_closed_when_service_key_is_unconfigured(self):
        response = self.client.post(
            "/notification/events/",
            {"event_type": "account_activation", "payload": {}},
            format="json",
            HTTP_X_INTERNAL_API_KEY="any-value",
        )

        self.assertEqual(response.status_code, 403)

    @patch("notification.views.process_event", return_value={"sent": 1, "failed": 0, "skipped": 0})
    def test_valid_internal_event_returns_dispatch_result(self, process_event):
        payload = {"email": "p0c@example.invalid", "token": "disposable-token"}
        response = self.client.post(
            "/notification/events/",
            {"event_type": "account_activation", "event_key": "p0c-event", "payload": payload},
            format="json",
            HTTP_X_INTERNAL_API_KEY="notification-test-only-key",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["success"])
        process_event.assert_called_once_with(
            event_type="account_activation",
            event_key="p0c-event",
            payload=payload,
        )
