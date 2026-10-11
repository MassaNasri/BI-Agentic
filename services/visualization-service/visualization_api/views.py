import logging

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from visualization_api.constants import normalize_chart_type, to_metabase_display
from visualization_api.services.chart_type_selector import select_chart_type_with_ollama
from visualization_api.services.chart_transformer import (
    ChartTransformationError,
    build_initial_visualization_spec,
)
from visualization_api.services import get_metabase_service
from visualization_api.models import VisualizationObjectOwnership
from visualization_api.services.query_authorization import QueryAuthorizationError, resolve_authorized_query

logger = logging.getLogger(__name__)


def _workspace_id(request):
    try:
        value = int(getattr(request.user, 'workspace_id', None))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _owned_object(workspace_id, object_type, object_id):
    try:
        object_id = int(object_id)
    except (TypeError, ValueError):
        return None
    return VisualizationObjectOwnership.objects.filter(
        workspace_id=workspace_id,
        object_type=object_type,
        metabase_object_id=object_id,
        ownership_status=VisualizationObjectOwnership.MAPPED,
    ).first()


class VisualizationHealthView(APIView):
    permission_classes = []

    def get(self, request):
        metabase = get_metabase_service()
        healthy = metabase.authenticate()
        return Response(
            {
                'success': healthy,
                'service': 'visualization-service',
                'error': metabase.last_error,
            },
            status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class CreateQuestionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        name = request.data.get('name', '')
        query_definition_id = str(request.data.get('query_definition_id') or '').strip()
        chart_type = request.data.get('chart_type')
        incoming_settings = request.data.get('visualization_settings')
        visualization_settings = incoming_settings if isinstance(incoming_settings, dict) else {}
        incoming_ai_trace = request.data.get('ai_trace')
        ai_trace = incoming_ai_trace if isinstance(incoming_ai_trace, dict) else {}
        chart_hint_from_ai = (
            chart_type
            or visualization_settings.get('chart_hint_from_ai')
            or visualization_settings.get('chart_type')
            or visualization_settings.get('display')
        )
        requested_chart_type = chart_hint_from_ai

        workspace_id = _workspace_id(request)
        if workspace_id is None:
            return Response({'success': False, 'error': 'Authenticated workspace claim is required.'}, status=403)
        if request.data.get('sql') and not query_definition_id:
            return Response(
                {'success': False, 'error': 'Raw SQL is not accepted; query_definition_id is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not name or not query_definition_id:
            return Response(
                {'success': False, 'error': 'name and query_definition_id are required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            authorized_query = resolve_authorized_query(
                definition_id=query_definition_id,
                authorization_header=str(request.META.get('HTTP_AUTHORIZATION') or ''),
                expected_workspace_id=workspace_id,
            )
        except QueryAuthorizationError as exc:
            return Response({'success': False, 'error': str(exc)}, status=exc.http_status)
        sanitized_sql = authorized_query.sql
        logger.info(
            "Visualization question request name=%s requested_chart_type=%s sql_len=%s sanitized_sql_len=%s",
            name,
            requested_chart_type or "",
            len(str(sanitized_sql or "")),
            len(str(sanitized_sql or "")),
        )
        chart_selection = select_chart_type_with_ollama(
            name=str(name),
            sql=str(sanitized_sql),
            requested_chart_type=str(requested_chart_type or ""),
            visualization_settings=visualization_settings,
            ai_trace=ai_trace,
        )
        selected_chart_type = normalize_chart_type(
            str(chart_selection.get("chart_type") or ""),
            default='table',
        )
        logger.info(
            "Visualization chart selected selected_chart_type=%s source=%s requested_chart_type=%s",
            selected_chart_type,
            chart_selection.get("source"),
            requested_chart_type or "",
        )

        metabase = get_metabase_service()
        if not metabase.authenticate():
            return Response(
                {'success': False, 'error': metabase.last_error or 'metabase_authentication_failed'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        query_metadata = {
            "result_shape": chart_selection.get("result_shape")
            if isinstance(chart_selection.get("result_shape"), dict)
            else {},
            "columns": (
                visualization_settings.get("dataset_columns")
                or visualization_settings.get("columns")
                or visualization_settings.get("result_columns")
                or []
            ),
        }
        try:
            visualization_spec = build_initial_visualization_spec(
                chart_type=selected_chart_type,
                query_metadata=query_metadata,
                recommendation_metadata=(
                    chart_selection.get("chart_recommendation")
                    if isinstance(chart_selection.get("chart_recommendation"), dict)
                    else None
                ),
            )
        except ChartTransformationError as exc:
            payload = exc.to_dict()
            payload["success"] = False
            return Response(payload, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        outbound_settings = dict(visualization_settings)
        outbound_settings.update(visualization_spec.metabase_config.visualization_settings)
        outbound_settings.update(
            {
                'chart_type': selected_chart_type,
                'display': visualization_spec.metabase_config.display,
                'chart_hint_from_ai': str(chart_hint_from_ai or ''),
                'chart_selection': chart_selection,
                'visualization_spec': visualization_spec.model_dump(mode="json"),
            }
        )

        question_id = metabase.create_question(
            name=name,
            sql=sanitized_sql,
            visualization_settings=outbound_settings,
        )

        if not question_id:
            return Response(
                {'success': False, 'error': metabase.last_error or 'question_creation_failed'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        try:
            ownership = VisualizationObjectOwnership.objects.create(
                workspace_id=workspace_id,
                object_type=VisualizationObjectOwnership.CARD,
                metabase_object_id=int(question_id),
                creator_id=str(getattr(request.user, 'id', '') or ''),
                query_definition_id=authorized_query.definition_id,
                source_context={'dataset_id': authorized_query.dataset_id},
            )
        except Exception:
            metabase.delete_question(question_id)
            logger.exception('Failed to persist application ownership for Metabase card')
            return Response(
                {'success': False, 'error': 'visualization_ownership_persistence_failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if not metabase.validate_question_execution(question_id):
            metabase.delete_question(question_id)
            ownership.delete()
            return Response(
                {
                    'success': False,
                    'error': 'question_execution_failed',
                    'details': metabase.last_error or 'metabase_question_runtime_failed',
                    'question_id': question_id,
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if not metabase.enable_question_embedding(question_id):
            metabase.delete_question(question_id)
            ownership.delete()
            return Response(
                {'success': False, 'error': metabase.last_error or 'question_embedding_enable_failed'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        if not metabase.validate_embedded_question_execution(question_id):
            metabase.delete_question(question_id)
            ownership.delete()
            return Response(
                {
                    'success': False,
                    'error': 'embedded_question_execution_failed',
                    'details': metabase.last_error or 'metabase_embed_runtime_failed',
                    'question_id': question_id,
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                'success': True,
                'question_id': question_id,
                'chart_hint_from_ai': str(chart_selection.get('chart_hint_from_ai') or chart_hint_from_ai or ''),
                'chart_type_selected_by_visualization_service': selected_chart_type,
                'chart_type': selected_chart_type or normalize_chart_type(
                    metabase.last_display if hasattr(metabase, 'last_display') else '',
                    default='table',
                ),
                'display': metabase.last_display if hasattr(metabase, 'last_display') else None,
                'metabase_display': metabase.last_display if hasattr(metabase, 'last_display') else None,
                'metabase_card_display': metabase.last_metabase_display if hasattr(metabase, 'last_metabase_display') else None,
                'metabase_visualization_settings': metabase.last_visualization_settings if hasattr(metabase, 'last_visualization_settings') else {},
                'fallback_applied': metabase.last_fallback_applied if hasattr(metabase, 'last_fallback_applied') else False,
                'fallback_reason': metabase.last_fallback_reason if hasattr(metabase, 'last_fallback_reason') else '',
                'chart_selection_source': chart_selection.get('source'),
                'chart_selection_reason': chart_selection.get('reason'),
                'result_shape': chart_selection.get('result_shape') if isinstance(chart_selection.get('result_shape'), dict) else {},
                'recommended_chart_type': chart_selection.get('recommended_chart_type'),
                'chart_recommendation': chart_selection.get('chart_recommendation') if isinstance(chart_selection.get('chart_recommendation'), dict) else {},
                'visualization_spec': visualization_spec.model_dump(mode='json'),
                'alternatives': chart_selection.get('alternatives') if isinstance(chart_selection.get('alternatives'), list) else [],
                'incompatible_chart_types': (
                    chart_selection.get('incompatible_chart_types')
                    if isinstance(chart_selection.get('incompatible_chart_types'), list)
                    else []
                ),
            },
            status=status.HTTP_200_OK,
        )


class CreateDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        name = request.data.get('name', '')
        description = request.data.get('description', '')

        workspace_id = _workspace_id(request)
        if workspace_id is None:
            return Response({'success': False, 'error': 'Authenticated workspace claim is required.'}, status=403)
        if not name:
            return Response(
                {'success': False, 'error': 'name is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        metabase = get_metabase_service()
        if not metabase.authenticate():
            return Response(
                {'success': False, 'error': metabase.last_error or 'metabase_authentication_failed'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        dashboard_id = metabase.create_dashboard(name=name, description=description)
        if not dashboard_id:
            return Response(
                {'success': False, 'error': metabase.last_error or 'dashboard_creation_failed'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        try:
            ownership = VisualizationObjectOwnership.objects.create(
                workspace_id=workspace_id,
                object_type=VisualizationObjectOwnership.DASHBOARD,
                metabase_object_id=int(dashboard_id),
                creator_id=str(getattr(request.user, 'id', '') or ''),
                source_context={},
            )
        except Exception:
            metabase.delete_dashboard(dashboard_id)
            logger.exception('Failed to persist application ownership for Metabase dashboard')
            return Response(
                {'success': False, 'error': 'dashboard_ownership_persistence_failed'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if not metabase.enable_dashboard_embedding(dashboard_id):
            metabase.delete_dashboard(dashboard_id)
            ownership.delete()
            return Response(
                {'success': False, 'error': metabase.last_error or 'dashboard_embedding_enable_failed'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {'success': True, 'dashboard_id': dashboard_id},
            status=status.HTTP_200_OK,
        )


class AddQuestionToDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        question_id = request.data.get('question_id')
        dashboard_id = request.data.get('dashboard_id')

        if question_id is None or dashboard_id is None:
            return Response(
                {'success': False, 'error': 'question_id and dashboard_id are required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        workspace_id = _workspace_id(request)
        card = _owned_object(workspace_id, VisualizationObjectOwnership.CARD, question_id)
        dashboard = _owned_object(workspace_id, VisualizationObjectOwnership.DASHBOARD, dashboard_id)
        if card is None or dashboard is None:
            return Response(
                {'success': False, 'error': 'Both card and dashboard must be mapped to this workspace.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        metabase = get_metabase_service()
        if not metabase.authenticate():
            return Response(
                {'success': False, 'error': metabase.last_error or 'metabase_authentication_failed'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        added = metabase.add_question_to_dashboard(question_id, dashboard_id)
        if not added:
            return Response(
                {'success': False, 'error': metabase.last_error or 'add_to_dashboard_failed'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({'success': True}, status=status.HTTP_200_OK)


class QuestionEmbedUrlView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, question_id):
        workspace_id = _workspace_id(request)
        if _owned_object(workspace_id, VisualizationObjectOwnership.CARD, question_id) is None:
            return Response({'success': False, 'error': 'Question is not owned by this workspace.'}, status=403)
        metabase = get_metabase_service()
        url = metabase.get_question_embed_url(question_id)
        if not url:
            return Response(
                {'success': False, 'error': metabase.last_error or 'question_embed_url_failed'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({'success': True, 'embed_url': url}, status=status.HTTP_200_OK)


class DashboardEmbedUrlView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, dashboard_id):
        workspace_id = _workspace_id(request)
        if _owned_object(workspace_id, VisualizationObjectOwnership.DASHBOARD, dashboard_id) is None:
            return Response({'success': False, 'error': 'Dashboard is not owned by this workspace.'}, status=403)
        metabase = get_metabase_service()
        url = metabase.get_dashboard_embed_url(dashboard_id)
        if not url:
            return Response(
                {'success': False, 'error': metabase.last_error or 'dashboard_embed_url_failed'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({'success': True, 'embed_url': url}, status=status.HTTP_200_OK)
