import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'service_config.settings')
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

import django
django.setup()
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory, force_authenticate

from visualization_api.services.query_authorization import (  # noqa: E402
    QueryAuthorizationError,
    resolve_authorized_query,
)
from visualization_api.views import (  # noqa: E402
    AddQuestionToDashboardView,
    DashboardEmbedUrlView,
    QuestionEmbedUrlView,
    CreateQuestionView,
)


def _principal(workspace_id='10'):
    return SimpleNamespace(is_authenticated=True, id='7', workspace_id=workspace_id)


class VisualizationSecurityTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def test_raw_sql_without_query_definition_is_rejected(self):
        request = self.factory.post('/visualization/question/create/', {'name': 'x', 'sql': 'SELECT 1'}, format='json')
        force_authenticate(request, user=_principal())
        response = CreateQuestionView.as_view()(request)
        self.assertEqual(response.status_code, 400)
        self.assertIn('Raw SQL is not accepted', response.data['error'])

    @patch('visualization_api.views._owned_object', return_value=None)
    def test_unmapped_or_foreign_card_cannot_be_embedded(self, owned):
        request = self.factory.get('/visualization/question/99/embed-url/')
        force_authenticate(request, user=_principal('10'))
        response = QuestionEmbedUrlView.as_view()(request, question_id=99)
        self.assertEqual(response.status_code, 403)

    @patch('visualization_api.views._owned_object')
    def test_both_card_and_dashboard_must_belong_to_workspace(self, owned):
        owned.side_effect = [Mock(), None]
        request = self.factory.post(
            '/visualization/dashboard/add-question/',
            {'question_id': 1, 'dashboard_id': 2},
            format='json',
        )
        force_authenticate(request, user=_principal('10'))
        response = AddQuestionToDashboardView.as_view()(request)
        self.assertEqual(response.status_code, 403)

    @patch('visualization_api.views._owned_object')
    def test_foreign_card_is_denied_even_when_dashboard_is_local(self, owned):
        owned.side_effect = [None, Mock()]
        request = self.factory.post(
            '/visualization/dashboard/add-question/',
            {'question_id': 1, 'dashboard_id': 2},
            format='json',
        )
        force_authenticate(request, user=_principal('10'))
        response = AddQuestionToDashboardView.as_view()(request)
        self.assertEqual(response.status_code, 403)

    @patch('visualization_api.views._owned_object', return_value=None)
    def test_unmapped_or_foreign_dashboard_cannot_be_embedded(self, owned):
        request = self.factory.get('/visualization/dashboard/99/embed-url/')
        force_authenticate(request, user=_principal('10'))
        response = DashboardEmbedUrlView.as_view()(request, dashboard_id=99)
        self.assertEqual(response.status_code, 403)

    @patch('visualization_api.views.get_metabase_service')
    @patch('visualization_api.views._owned_object', side_effect=[Mock(), Mock()])
    def test_same_tenant_card_and_dashboard_can_be_attached(self, owned, metabase_factory):
        metabase = metabase_factory.return_value
        metabase.authenticate.return_value = True
        metabase.add_question_to_dashboard.return_value = True
        request = self.factory.post(
            '/visualization/dashboard/add-question/',
            {'question_id': 1, 'dashboard_id': 2},
            format='json',
        )
        force_authenticate(request, user=_principal('10'))
        response = AddQuestionToDashboardView.as_view()(request)
        self.assertEqual(response.status_code, 200)

    @patch.dict(os.environ, {'METABASE_SECRET_KEY': 'test-only-secret', 'METABASE_EMBED_EXP_SECONDS': '300'})
    def test_embed_lifetime_is_capped_at_five_minutes(self):
        from visualization_api.services.jwt_embedding import JWTEmbeddingService

        service = JWTEmbeddingService()
        with self.assertRaises(ValueError):
            service.generate_embed_token({'question': 1}, exp_seconds=301)


@patch('visualization_api.services.query_authorization.requests.get')
def test_query_definition_response_cannot_cross_tenant(get):
    get.return_value.status_code = 200
    get.return_value.json.return_value = {
        'workspace_id': 11,
        'dataset_id': 2,
        'sql': 'SELECT 1',
    }
    try:
        resolve_authorized_query(
            definition_id='a-definition',
            authorization_header='Bearer test',
            expected_workspace_id=10,
        )
    except QueryAuthorizationError as exc:
        assert exc.http_status == 403
    else:
        raise AssertionError('cross-tenant query definition accepted')
