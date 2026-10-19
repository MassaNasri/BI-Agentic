from types import SimpleNamespace
from unittest.mock import patch
import uuid
import os
import subprocess
import sys
from pathlib import Path

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from .models import Payment, Plan, Subscription


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


class PaymentBoundaryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=SimpleNamespace(is_authenticated=True, id=41, role='manager'))
        self.plan = Plan.objects.create(
            name='Team', price_monthly='10.00', price_yearly='100.00',
            duration_days=30, max_voice_requests=100,
        )
        self.payload = {'workspace_id': 7, 'plan_id': self.plan.id, 'payment_method': 'visa'}
        self.key = str(uuid.uuid4())

    def post(self, payload=None, key=None):
        return self.client.post('/subscription/subscribe/', payload or self.payload,
                                format='json', HTTP_IDEMPOTENCY_KEY=key or self.key)

    def test_default_disabled_never_creates_entitlement(self):
        response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(Subscription.objects.exists())
        self.assertFalse(Payment.objects.exists())

    def test_production_startup_rejects_sandbox_mode(self):
        root = Path(__file__).resolve().parents[1]
        environment = os.environ.copy()
        environment.update({
            'APP_ENV': 'production', 'PAYMENT_MODE': 'sandbox',
            'DJANGO_SECRET_KEY': 'strong-key-for-configuration-test-0123456789',
            'DB_PASSWORD': 'strong-database-password-for-test',
            'ALLOWED_HOSTS': 'subscription.example',
        })
        result = subprocess.run(
            [sys.executable, '-c', 'import service_config.settings'],
            cwd=root, env=environment, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Production payment simulation is forbidden', result.stderr)

    @override_settings(PAYMENT_MODE='sandbox', APP_ENV='production')
    def test_production_rejects_sandbox_even_if_runtime_setting_is_changed(self):
        self.assertEqual(self.post().status_code, 503)
        self.assertFalse(Subscription.objects.exists())

    @override_settings(PAYMENT_MODE='sandbox', APP_ENV='test')
    @patch('subscription.views.get_notification_client')
    @patch('subscription.views._resolve_workspace_for_manager_or_admin')
    def test_sandbox_replay_is_idempotent(self, workspace, notifications):
        workspace.return_value = {'id': 7, 'manager_id': 41, 'owner': {}}
        notifications.return_value.send_event.return_value = {'success': True}
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(Subscription.objects.filter(is_active=True).count(), 1)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(notifications.return_value.send_event.call_count, 1)

    @override_settings(PAYMENT_MODE='sandbox', APP_ENV='test')
    @patch('subscription.views._resolve_workspace_for_manager_or_admin')
    def test_forged_state_and_cross_workspace_denied(self, workspace):
        workspace.return_value = {'id': 7, 'manager_id': 41, 'owner': {}}
        self.assertEqual(self.post({**self.payload, 'payment_status': 'success'}).status_code, 400)
        self.assertEqual(self.post({**self.payload, 'payment_success': True}).status_code, 400)
        self.assertEqual(self.post({**self.payload, 'amount': '0.00'}).status_code, 400)
        self.assertEqual(self.post({**self.payload, 'price': '0.01'}).status_code, 400)
        self.assertEqual(self.post({**self.payload, 'transaction_id': 'forged'}).status_code, 400)
        self.assertEqual(self.post({**self.payload, 'is_active': True}).status_code, 400)
        self.assertEqual(self.post({**self.payload, 'plan_id': 99999}).status_code, 400)
        self.plan.is_active = False
        self.plan.save(update_fields=['is_active'])
        self.assertEqual(self.post().status_code, 400)
        self.plan.is_active = True
        self.plan.save(update_fields=['is_active'])
        workspace.return_value = None
        self.assertEqual(self.post().status_code, 404)
        self.assertFalse(Subscription.objects.exists())

    @override_settings(PAYMENT_MODE='sandbox', APP_ENV='test')
    def test_anonymous_member_and_mismatched_workspace_cannot_activate(self):
        self.client.force_authenticate(user=None)
        self.assertIn(self.post().status_code, (401, 403))
        self.client.force_authenticate(user=SimpleNamespace(is_authenticated=True, id=41, role='member'))
        self.assertEqual(self.post().status_code, 403)
        self.client.force_authenticate(user=SimpleNamespace(is_authenticated=True, id=41, role='manager'))
        with patch('subscription.views._http_get_json', return_value=(200, {
            'success': True, 'id': 8, 'manager_id': 41, 'workspace': {'id': 8},
        })):
            self.assertEqual(self.post().status_code, 404)
        self.assertFalse(Subscription.objects.exists())

    @override_settings(PAYMENT_MODE='sandbox', APP_ENV='test')
    @patch('subscription.views.get_notification_client')
    @patch('subscription.views._resolve_workspace_for_manager_or_admin')
    def test_replayed_key_cannot_change_plan_and_sandbox_is_not_revenue(self, workspace, notifications):
        workspace.return_value = {'id': 7, 'manager_id': 41, 'owner': {}}
        notifications.return_value.send_event.return_value = {'success': True}
        self.assertEqual(self.post().status_code, 201)
        other = Plan.objects.create(name='Other', price_monthly='50.00', price_yearly='500.00',
                                    duration_days=30, max_voice_requests=500)
        self.assertEqual(self.post({**self.payload, 'plan_id': other.id}).status_code, 409)
        self.assertEqual(Subscription.objects.count(), 1)
        with patch('subscription.views._fetch_auth_users_summary', return_value=({'total': 0, 'active': 0, 'admins': 0}, None)), \
             patch('subscription.views._fetch_workspace_total', return_value=(0, None)):
            self.client.force_authenticate(user=SimpleNamespace(is_authenticated=True, id=41, role='admin'))
            response = self.client.get('/admin/stats/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['payments'], {'count': 0, 'revenue': '0.00'})


class LegacyPaymentMigrationTests(TransactionTestCase):
    def test_legacy_simulated_access_is_quarantined_and_reverse_does_not_reactivate(self):
        before = [('subscription', '0002_plan_metadata_fields')]
        after = [('subscription', '0003_payment_request_key_payment_source')]
        executor = MigrationExecutor(connection)
        try:
            executor.migrate(before)
            old_apps = executor.loader.project_state(before).apps
            plan = old_apps.get_model('subscription', 'Plan').objects.create(
                name='Legacy', price_monthly='10.00', price_yearly='100.00',
                duration_days=30, max_voice_requests=100,
            )
            old_apps.get_model('subscription', 'Subscription').objects.create(
                workspace_id=91, plan=plan, is_active=True,
            )
            executor = MigrationExecutor(connection)
            executor.migrate(after)
            self.assertFalse(Subscription.objects.get(workspace_id=91).is_active)
            executor = MigrationExecutor(connection)
            executor.migrate(before)
            old_apps = executor.loader.project_state(before).apps
            self.assertFalse(old_apps.get_model('subscription', 'Subscription').objects.get(workspace_id=91).is_active)
        finally:
            MigrationExecutor(connection).migrate(after)
