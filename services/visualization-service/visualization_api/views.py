from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from visualization_api.constants import normalize_chart_type, to_metabase_display
from visualization_api.services import get_metabase_service


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
        sql = request.data.get('sql', '')
        chart_type = request.data.get('chart_type')
        incoming_settings = request.data.get('visualization_settings')
        visualization_settings = incoming_settings if isinstance(incoming_settings, dict) else {}
        requested_chart_type = chart_type or visualization_settings.get('display') or visualization_settings.get('chart_type')
        normalized_chart_type = normalize_chart_type(requested_chart_type, default='')

        if not name or not sql:
            return Response(
                {'success': False, 'error': 'name and sql are required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        metabase = get_metabase_service()
        if not metabase.authenticate():
            return Response(
                {'success': False, 'error': metabase.last_error or 'metabase_authentication_failed'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        outbound_settings = dict(visualization_settings)
        if normalized_chart_type:
            outbound_settings.update(
                {
                    'chart_type': normalized_chart_type,
                    'display': to_metabase_display(normalized_chart_type),
                }
            )

        question_id = metabase.create_question(
            name=name,
            sql=sql,
            visualization_settings=outbound_settings,
        )

        if not question_id:
            return Response(
                {'success': False, 'error': metabase.last_error or 'question_creation_failed'},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        metabase.enable_question_embedding(question_id)

        return Response(
            {
                'success': True,
                'question_id': question_id,
                'chart_type': normalized_chart_type or normalize_chart_type(
                    metabase.last_display if hasattr(metabase, 'last_display') else '',
                    default='table',
                ),
                'display': metabase.last_display if hasattr(metabase, 'last_display') else None,
                'fallback_applied': metabase.last_fallback_applied if hasattr(metabase, 'last_fallback_applied') else False,
                'fallback_reason': metabase.last_fallback_reason if hasattr(metabase, 'last_fallback_reason') else '',
            },
            status=status.HTTP_200_OK,
        )


class CreateDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        name = request.data.get('name', '')
        description = request.data.get('description', '')

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

        metabase.enable_dashboard_embedding(dashboard_id)

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
        metabase = get_metabase_service()
        url = metabase.get_dashboard_embed_url(dashboard_id)
        if not url:
            return Response(
                {'success': False, 'error': metabase.last_error or 'dashboard_embed_url_failed'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({'success': True, 'embed_url': url}, status=status.HTTP_200_OK)
