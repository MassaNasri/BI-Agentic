"""
Voice Reports Views

API endpoints for voice-driven BI system.
Orchestrates Small Whisper, ClickHouse, and Metabase.
"""


from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework import status
from django.shortcuts import get_object_or_404
from django.db.models import Sum
from django.db.models.functions import Coalesce
import logging
import os
import requests

from .models import VoiceReport, SQLEditHistory
from .constants import ChartType, normalize_chart_type
from .services import (
    get_small_whisper_client,
    get_clickhouse_executor,
    SQLGuard,
    get_metabase_service,
    get_event_publisher,
)
from .services.clickhouse_executor import sanitize_query_results
from users.permissions import IsManager, IsAnalyst, IsExecutive

logger = logging.getLogger(__name__)


def publish_kafka_event(topic, payload, key=None):
    """
    Publish workflow events without impacting API responses on broker failures.
    """
    try:
        publisher = get_event_publisher()
        publisher.publish(topic=topic, payload=payload, key=key)
    except Exception as exc:
        logger.warning("Kafka publish skipped topic=%s error=%s", topic, exc)


def normalize_chart_payload(chart_payload):
    """
    Normalize chart payloads coming from external components (e.g., Small Whisper).
    """
    if not isinstance(chart_payload, dict):
        return chart_payload
    raw_type = chart_payload.get("type")
    normalized_type = normalize_chart_type(raw_type, default=ChartType.TABLE)
    if raw_type and raw_type != normalized_type:
        logger.info(
            "Chart type mapping applied: source=%s mapped=%s",
            raw_type,
            normalized_type,
        )
    normalized_payload = dict(chart_payload)
    normalized_payload["type"] = normalized_type
    return normalized_payload


def get_user_workspace(user):
    """
    Get the user's workspace based on their role.
    
    - Manager: Returns their owned workspace
    - Analyst/Executive: Returns workspace they're a member of
    """
    if user.role == 'manager':
        # Manager owns workspace
        workspace = user.owned_workspaces.first()
        return workspace
    else:
        # Analyst or Executive is a member
        membership = user.workspace_memberships.filter(status='active').first()
        if membership:
            return membership.workspace
        return None


def get_report_embed_url(report, metabase_service=None):
    """
    Generate a fresh Metabase question embed URL for every response.
    """
    if not report.metabase_question_id:
        return ""

    metabase = metabase_service or get_metabase_service()
    embed_url = metabase.get_question_embed_url(report.metabase_question_id)
    if embed_url:
        return embed_url

    logger.warning(
        "Failed to generate dynamic embed URL for report=%s question=%s error=%s",
        report.id,
        report.metabase_question_id,
        metabase.last_error
    )
    return ""


class VoiceUploadView(APIView):
    """
    Upload audio file and get transcription + generated SQL from Small Whisper.
    
    Manager only.
    
    ARCHITECTURAL SEPARATION:
    - This endpoint (Main BI Backend) handles ALL authentication and user validation
    - Small Whisper Backend (port 8001) is a STATELESS AI worker
    - Small Whisper receives ONLY audio file, returns ONLY data (no user context)
    - This endpoint ALWAYS returns a valid report_id (even for conversational questions)
    """
    permission_classes = [IsAuthenticated, IsManager]
    parser_classes = [MultiPartParser, FormParser]
    
    def post(self, request):
        try:
            # Validate audio file
            if 'audio' not in request.FILES:
                return Response(
                    {'success': False, 'error': 'No audio file provided'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            audio_file = request.FILES['audio']
            workspace = get_user_workspace(request.user)
            
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Save audio file
            audio_dir = f'media/workspaces/{workspace.id}/audio'
            os.makedirs(audio_dir, exist_ok=True)
            
            # Generate unique filename
            import uuid
            filename = f"{uuid.uuid4()}_{audio_file.name}"
            audio_path = os.path.join(audio_dir, filename)
            
            with open(audio_path, 'wb+') as destination:
                for chunk in audio_file.chunks():
                    destination.write(chunk)
            
            logger.info(f"Audio file saved: {audio_path}")
            
            # Call Small Whisper (STATELESS - no user context needed)
            whisper_client = get_small_whisper_client()
            whisper_result = whisper_client.process_audio(audio_file=audio_path)
            
            if not whisper_result['success']:
                return Response(
                    {
                        'success': False,
                        'error': f"Small Whisper error: {whisper_result.get('error')}"
                    },
                    status=status.HTTP_503_SERVICE_UNAVAILABLE
                )
            
            # Extract question type and SQL
            question_type = whisper_result.get('question_type', 'unknown')
            sql = whisper_result.get('sql')
            
            # ALWAYS create a report record, even for conversational questions
            # This ensures we always return a valid report_id
            report = VoiceReport.objects.create(
                workspace=workspace,
                created_by=request.user,
                audio_file=audio_path,
                transcription=whisper_result['text'],
                intent_json=whisper_result.get('intent'),
                generated_sql=sql or '',  # Empty string if no SQL
                final_sql=sql or '',  # Initially same
                status=(
                    VoiceReport.STATUS_PENDING
                    if (question_type == 'analytical' and sql)
                    else VoiceReport.STATUS_UPLOADED
                )
            )

            event_base = {
                'report_id': report.id,
                'workspace_id': workspace.id,
                'user_id': request.user.id,
                'question_type': question_type,
            }
            publish_kafka_event(
                'report.voice.received',
                {
                    **event_base,
                    'transcription': whisper_result.get('text', ''),
                },
                key=str(report.id),
            )
            if whisper_result.get('intent') is not None:
                publish_kafka_event(
                    'report.intent.generated',
                    {
                        **event_base,
                        'intent': whisper_result.get('intent'),
                    },
                    key=str(report.id),
                )
            if sql:
                publish_kafka_event(
                    'report.sql.generated',
                    {
                        **event_base,
                        'sql': sql,
                    },
                    key=str(report.id),
                )

            # Analytical questions must produce SQL. If not, surface a hard failure
            # instead of silently treating it as conversational.
            if question_type == 'analytical' and not sql:
                analytical_error_message = whisper_result.get(
                    'message',
                    'Analytical question detected but SQL generation failed.'
                )
                report.status = VoiceReport.STATUS_FAILED
                report.error_message = analytical_error_message
                report.save(update_fields=['status', 'error_message'])
                logger.error(
                    "Analytical SQL generation failed for report=%s workspace=%s message=%s",
                    report.id,
                    workspace.id,
                    analytical_error_message,
                )
                return Response(
                    {
                        'success': False,
                        'id': report.id,
                        'report_id': report.id,
                        'question_type': question_type,
                        'requires_sql': True,
                        'error': 'SQL generation failed for analytical question',
                        'details': analytical_error_message,
                        'status': VoiceReport.STATUS_FAILED,
                    },
                    status=status.HTTP_502_BAD_GATEWAY
                )
            
            # Handle conversational questions (no SQL needed)
            if question_type != 'analytical' or not sql:
                logger.info(f"Conversational question detected: {whisper_result.get('message')}")
                return Response({
                    'success': True,
                    'id': report.id,  # Always return valid report_id
                    'report_id': report.id,  # For backward compatibility
                    'transcription': whisper_result['text'],
                    'question_type': question_type,
                    'message': whisper_result.get('message', 'Question does not require data analysis'),
                    'intent': whisper_result.get('intent'),
                    'requires_sql': False,
                    'status': VoiceReport.STATUS_UPLOADED
                })
            
            # TODO: Create history entry when ReportHistory model is added
            # ReportHistory.objects.create(
            #     report=report,
            #     action='created',
            #     performed_by=request.user,
            #     changes={
            #         'transcription': whisper_result['text'],
            #         'sql': whisper_result['sql']
            #     }
            # )
            
            logger.info(f"Voice report created: {report.id}")

            normalized_chart = normalize_chart_payload(whisper_result.get('chart'))
            
            return Response({
                'success': True,
                'id': report.id,  # Always return valid report_id
                'report_id': report.id,  # For backward compatibility
                'transcription': whisper_result['text'],
                'question_type': question_type,
                'intent': whisper_result.get('intent'),
                'sql': sql,
                'chart': normalized_chart,
                'confidence': whisper_result.get('confidence'),
                'message': 'Audio processed successfully. Ready to execute.',
                'status': VoiceReport.STATUS_PENDING
            })
        
        except Exception as e:
            logger.error(f"Error in VoiceUploadView: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class QueryExecuteView(APIView):
    """
    Execute SQL query on ClickHouse and create Metabase visualization.
    
    Manager and Analyst can execute.
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request, report_id):
        try:
            # Validate report_id is not None/undefined
            if report_id is None:
                logger.error("QueryExecuteView called with None report_id")
                return Response(
                    {'success': False, 'error': 'Invalid report_id: report_id cannot be null or undefined'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get report
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            report = get_object_or_404(
                VoiceReport,
                id=report_id,
                workspace=workspace
            )
            
            # Validate report has SQL to execute
            if not report.final_sql or not report.final_sql.strip():
                logger.warning(f"Report {report_id} has no SQL to execute")
                return Response(
                    {'success': False, 'error': 'This report does not contain a SQL query. It may be a conversational question.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validate permissions
            if request.user.role not in ['manager', 'analyst']:
                return Response(
                    {'success': False, 'error': 'Permission denied'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Get SQL (final_sql may be edited by analyst)
            sql_to_execute = report.final_sql
            
            # Validate SQL with SQL Guard
            guard = SQLGuard(
                workspace_database=os.getenv('CLICKHOUSE_DATABASE', 'etl')
            )
            
            is_valid, error_msg, clean_sql = guard.validate_and_sanitize(sql_to_execute)
            
            if not is_valid:
                report.status = VoiceReport.STATUS_FAILED
                report.error_message = f"SQL validation failed: {error_msg}"
                report.save()
                
                return Response(
                    {'success': False, 'error': error_msg},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            report.sql_validated = True
            report.final_sql = clean_sql
            report.status = VoiceReport.STATUS_PROCESSING
            report.error_message = ''
            report.save()
            
            # Execute through Query Service (REST), with local fallback for resilience.
            query_result = self._execute_query_with_query_service(request, clean_sql)

            if not query_result.get('success'):
                report.status = VoiceReport.STATUS_FAILED
                report.error_message = query_result.get('error', 'Query execution failed')
                report.save()

                logger.error(
                    "Query execution failed for report %s: %s",
                    report.id,
                    query_result.get('error')
                )

                return Response(
                    {
                        'success': False,
                        'error': 'Query execution failed',
                        'details': query_result.get('error', 'query_service_failure')
                    },
                    status=status.HTTP_502_BAD_GATEWAY
                )
            
            # Save query results
            # 🔒 NaN-SAFE: Apply sanitization before saving to PostgreSQL JSONField
            # This is defense-in-depth - results are already sanitized in executor,
            # but we sanitize again here to ensure PostgreSQL storage never fails
            sanitized_rows = sanitize_query_results(query_result['rows'])
            report.query_result = {
                'columns': query_result.get('columns', []),
                'rows': sanitized_rows
            }
            report.execution_time_ms = query_result['execution_time_ms']
            report.row_count = query_result['row_count']
            report.status = VoiceReport.STATUS_EXECUTED
            logger.info(
                "ClickHouse result ready for report %s: columns=%s row_count=%s",
                report.id,
                len(query_result.get('columns', [])),
                query_result['row_count']
            )
            
            # 🔒 NaN-SAFE: Catch JSON serialization errors during save
            # This is a final safety net in case any NaN/Infinity values slip through
            try:
                report.save()
            except (ValueError, TypeError) as json_error:
                # JSON serialization failed - likely NaN/Infinity in data
                logger.error(f"JSON serialization error when saving report {report.id}: {json_error}")
                logger.error(f"This indicates NaN/Infinity values weren't properly sanitized")
                # Try one more sanitization pass and save again
                sanitized_rows = sanitize_query_results(sanitized_rows)
                report.query_result = {
                    'columns': query_result.get('columns', []),
                    'rows': sanitized_rows
                }
                try:
                    report.save()
                except Exception as final_error:
                    # If it still fails after re-sanitization, return error
                    report.status = VoiceReport.STATUS_FAILED
                    report.error_message = f"Data serialization error: {str(final_error)}"
                    report.save()
                    return Response(
                        {
                            'success': False,
                            'error': 'Failed to save query results: invalid numeric values detected',
                            'details': str(final_error)
                        },
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )

            publish_kafka_event(
                'report.query.executed',
                {
                    'report_id': report.id,
                    'workspace_id': report.workspace_id,
                    'user_id': request.user.id,
                    'row_count': query_result.get('row_count', 0),
                    'execution_time_ms': query_result.get('execution_time_ms', 0),
                },
                key=str(report.id),
            )
            
            # Infer chart type
            chart_type = self._infer_chart_type(
                query_result['columns'],
                query_result['rows'],
                report.intent_json
            )
            report.chart_type = chart_type
            
            # Create visualization through Visualization Service.
            visualization_result = self._create_visualization_with_service(
                request=request,
                report=report,
                sql=clean_sql,
                chart_type=chart_type,
            )
            if not visualization_result.get('success'):
                return self._metabase_failure_response(
                    report=report,
                    chart_type=chart_type,
                    row_count=query_result['row_count'],
                    execution_time_ms=query_result['execution_time_ms'],
                    failure_reason=visualization_result.get('failure_reason', 'visualization_service_failed'),
                    details=visualization_result.get('error'),
                    http_status=visualization_result.get('http_status', status.HTTP_502_BAD_GATEWAY),
                    clear_question=visualization_result.get('clear_question', True),
                )

            question_id = visualization_result.get('question_id')
            dashboard_id = visualization_result.get('dashboard_id')
            embed_url = visualization_result.get('embed_url', '')
            report.metabase_question_id = question_id
            report.metabase_dashboard_id = dashboard_id
            
            # TODO: Save chart inference when ChartInference model is added
            # ChartInference.objects.create(
            #     report=report,
            #     inferred_type=chart_type,
            #     column_analysis={
            #         'columns': query_result['columns'],
            #         'row_count': query_result['row_count']
            #     },
            #     confidence_score=0.85
            # )
            
            report.chart_type = chart_type
            report.status = VoiceReport.STATUS_VISUALIZATION_CREATED
            report.error_message = ''
            report.embed_url = ''
            report.save()

            publish_kafka_event(
                'report.visualization.ready',
                {
                    'report_id': report.id,
                    'workspace_id': report.workspace_id,
                    'user_id': request.user.id,
                    'metabase_question_id': question_id,
                    'metabase_dashboard_id': dashboard_id,
                },
                key=str(report.id),
            )
            
            # TODO: Create history entry when ReportHistory model is added
            # ReportHistory.objects.create(
            #     report=report,
            #     action='executed',
            #     performed_by=request.user,
            #     changes={
            #         'row_count': query_result['row_count'],
            #         'execution_time_ms': query_result['execution_time_ms'],
            #         'chart_type': chart_type
            #     }
            # )
            
            logger.info(f"Report {report.id} executed successfully")
            
            return Response({
                'success': True,
                'report_id': report.id,
                'row_count': query_result['row_count'],
                'execution_time_ms': query_result['execution_time_ms'],
                'chart_type': chart_type,
                'status': report.status,
                'embed_url': embed_url,
                'metabase_question_id': question_id
            })
        
        except Exception as e:
            logger.error(f"Error in QueryExecuteView: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _metabase_failure_response(
        self,
        *,
        report,
        chart_type,
        row_count,
        execution_time_ms,
        failure_reason,
        http_status,
        details=None,
        clear_question=True
    ):
        """Persist visualization failure and return a structured API error."""
        logger.error(
            "Metabase visualization failed for report %s: reason=%s details=%s",
            report.id,
            failure_reason,
            details
        )
        report.status = VoiceReport.STATUS_FAILED
        report.error_message = (
            f"metabase_visualization_failed: {failure_reason}"
            if not details
            else f"metabase_visualization_failed: {failure_reason} ({details})"
        )
        report.embed_url = ''
        if clear_question:
            report.metabase_question_id = None
            report.metabase_dashboard_id = None
        report.save()

        response_payload = {
            'success': False,
            'error': 'metabase_visualization_failed',
            'report_id': report.id,
            'row_count': row_count,
            'execution_time_ms': execution_time_ms,
            'chart_type': chart_type,
        }
        if details:
            response_payload['details'] = details

        return Response(response_payload, status=http_status)
    
    def _infer_chart_type(self, columns, rows, intent):
        """Infer appropriate chart type from data and intent."""
        raw_chart_type = ChartType.TABLE

        if not rows:
            return ChartType.TABLE
        
        num_columns = len(columns)
        
        # Single value -> number display
        if num_columns == 1 and len(rows) == 1:
            raw_chart_type = 'scalar'
        elif num_columns == 2:
            # Check if first column is date/time
            first_col_name = columns[0].lower()
            if any(term in first_col_name for term in ['date', 'time', 'year', 'month', 'day']):
                raw_chart_type = ChartType.LINE
            else:
                raw_chart_type = ChartType.BAR
        elif num_columns > 2:
            # Multiple numeric columns -> bar chart
            raw_chart_type = ChartType.BAR
        
        normalized_chart_type = normalize_chart_type(raw_chart_type, default=ChartType.TABLE)
        if raw_chart_type != normalized_chart_type:
            logger.info(
                "Chart type mapping applied in QueryExecuteView: source=%s mapped=%s",
                raw_chart_type,
                normalized_chart_type,
            )
        return normalized_chart_type
    
    def _service_headers(self, request):
        headers = {'Content-Type': 'application/json'}
        auth_header = request.META.get('HTTP_AUTHORIZATION')
        if auth_header:
            headers['Authorization'] = auth_header
        return headers

    def _response_error_message(self, response, default):
        try:
            payload = response.json()
            if isinstance(payload, dict):
                return payload.get('error') or payload.get('message') or default
        except Exception:
            pass
        return (response.text or default)[:500]

    def _execute_query_with_query_service(self, request, clean_sql):
        query_service_url = os.getenv('QUERY_SERVICE_URL', 'http://query-service:8006').rstrip('/')
        payload = {
            'sql': clean_sql,
            'workspace_database': os.getenv('CLICKHOUSE_DATABASE', 'etl'),
        }

        try:
            response = requests.post(
                f'{query_service_url}/query/execute/',
                json=payload,
                headers=self._service_headers(request),
                timeout=120,
            )
            if response.status_code == status.HTTP_200_OK:
                result = response.json()
                if result.get('success'):
                    return result
                return {
                    'success': False,
                    'error': result.get('error', 'query_service_execution_failed'),
                }

            return {
                'success': False,
                'error': self._response_error_message(response, 'query_service_execution_failed'),
            }
        except requests.RequestException as exc:
            logger.warning("Query service unavailable, using local fallback: %s", exc)

        # Fallback keeps behavior stable if query-service is temporarily unavailable.
        try:
            executor = get_clickhouse_executor()
            return executor.execute_query(clean_sql)
        except Exception as exc:
            return {
                'success': False,
                'error': f'query_service_and_fallback_failed: {exc}',
            }

    def _create_visualization_with_service(self, request, report, sql, chart_type):
        visualization_service_url = os.getenv(
            'VISUALIZATION_SERVICE_URL',
            'http://visualization-service:8007'
        ).rstrip('/')
        headers = self._service_headers(request)
        try:
            question_response = requests.post(
                f'{visualization_service_url}/visualization/question/create/',
                json={
                    'name': f"Voice Report #{report.id}: {report.transcription[:50]}",
                    'sql': sql,
                    'chart_type': chart_type,
                },
                headers=headers,
                timeout=120,
            )
        except requests.RequestException as exc:
            return {
                'success': False,
                'failure_reason': 'question_creation_failed',
                'error': f'visualization_service_unavailable: {exc}',
                'http_status': status.HTTP_502_BAD_GATEWAY,
            }
        if question_response.status_code != status.HTTP_200_OK:
            return {
                'success': False,
                'failure_reason': 'question_creation_failed',
                'error': self._response_error_message(question_response, 'question_creation_failed'),
                'http_status': status.HTTP_502_BAD_GATEWAY,
            }

        question_payload = question_response.json()
        question_id = question_payload.get('question_id')
        if not question_id:
            return {
                'success': False,
                'failure_reason': 'question_creation_failed',
                'error': 'visualization_service_missing_question_id',
                'http_status': status.HTTP_502_BAD_GATEWAY,
            }

        dashboard_id = self._get_or_create_dashboard(
            workspace=report.workspace,
            visualization_service_url=visualization_service_url,
            headers=headers,
        )

        if dashboard_id:
            try:
                requests.post(
                    f'{visualization_service_url}/visualization/dashboard/add-question/',
                    json={'question_id': question_id, 'dashboard_id': dashboard_id},
                    headers=headers,
                    timeout=60,
                )
            except requests.RequestException as exc:
                logger.warning(
                    "Failed adding question %s to dashboard %s: %s",
                    question_id,
                    dashboard_id,
                    exc
                )

        try:
            embed_response = requests.get(
                f'{visualization_service_url}/visualization/question/{question_id}/embed-url/',
                headers=headers,
                timeout=60,
            )
        except requests.RequestException as exc:
            return {
                'success': False,
                'failure_reason': 'embed_generation_failed',
                'error': f'visualization_service_unavailable: {exc}',
                'http_status': status.HTTP_502_BAD_GATEWAY,
                'clear_question': False,
            }
        if embed_response.status_code != status.HTTP_200_OK:
            return {
                'success': False,
                'failure_reason': 'embed_generation_failed',
                'error': self._response_error_message(embed_response, 'embed_generation_failed'),
                'http_status': status.HTTP_502_BAD_GATEWAY,
                'clear_question': False,
            }

        embed_payload = embed_response.json()
        embed_url = embed_payload.get('embed_url')
        if not embed_url:
            return {
                'success': False,
                'failure_reason': 'embed_generation_failed',
                'error': 'visualization_service_missing_embed_url',
                'http_status': status.HTTP_502_BAD_GATEWAY,
                'clear_question': False,
            }

        return {
            'success': True,
            'question_id': question_id,
            'dashboard_id': dashboard_id,
            'embed_url': embed_url,
        }

    def _get_or_create_dashboard(self, workspace, visualization_service_url, headers):
        """Get an existing workspace dashboard ID or create one through visualization service."""
        existing_report = VoiceReport.objects.filter(
            workspace=workspace,
            metabase_dashboard_id__isnull=False
        ).first()
        if existing_report:
            return existing_report.metabase_dashboard_id
        try:
            response = requests.post(
                f'{visualization_service_url}/visualization/dashboard/create/',
                json={
                    'name': f'Workspace {workspace.id} - Voice Reports',
                    'description': f'Voice-driven reports for {workspace.name}',
                },
                headers=headers,
                timeout=120,
            )
        except requests.RequestException as exc:
            logger.warning(
                "Failed to create dashboard for workspace=%s due to connectivity error=%s",
                workspace.id,
                exc
            )
            return None
        if response.status_code != status.HTTP_200_OK:
            logger.warning(
                "Failed to create dashboard for workspace=%s error=%s",
                workspace.id,
                self._response_error_message(response, 'dashboard_creation_failed')
            )
            return None

        payload = response.json()
        return payload.get('dashboard_id')


class SQLEditView(APIView):
    """
    Edit SQL query (Analyst only).
    """
    permission_classes = [IsAuthenticated, IsAnalyst]
    
    def put(self, request, report_id):
        try:
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            report = get_object_or_404(
                VoiceReport,
                id=report_id,
                workspace=workspace
            )
            
            new_sql = request.data.get('sql')
            
            if not new_sql:
                return Response(
                    {'success': False, 'error': 'SQL is required'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Validate new SQL
            guard = SQLGuard(
                workspace_database=os.getenv('CLICKHOUSE_DATABASE', 'default')
            )
            
            is_valid, error_msg, clean_sql = guard.validate_and_sanitize(new_sql)
            
            if not is_valid:
                return Response(
                    {'success': False, 'error': error_msg},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Save old SQL for history
            old_sql = report.final_sql
            
            # Update report
            report.final_sql = clean_sql
            report.sql_edited = True
            report.edited_by = request.user
            report.sql_validated = True
            report.status = VoiceReport.STATUS_PENDING  # Needs re-execution
            report.save()
            
            # TODO: Create history entry when ReportHistory model is added
            # ReportHistory.objects.create(
            #     report=report,
            #     action='sql_edited',
            #     performed_by=request.user,
            #     changes={
            #         'old_sql': old_sql,
            #         'new_sql': clean_sql
            #     }
            # )
            
            logger.info(f"Report {report.id} SQL edited by analyst {request.user.email}")
            
            return Response({
                'success': True,
                'report_id': report.id,
                'sql': clean_sql,
                'message': 'SQL updated successfully. Ready to re-execute.'
            })
        
        except Exception as e:
            logger.error(f"Error in SQLEditView: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ReportListView(APIView):
    """
    List all reports for workspace.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            reports = VoiceReport.objects.filter(
                workspace=workspace
            ).order_by('-created_at')
            
            # Filter by role
            if request.user.role == 'manager':
                # Manager sees only their own reports
                reports = reports.filter(created_by=request.user)
            # Analyst and Executive see all workspace reports
            
            metabase = get_metabase_service()
            data = []
            for report in reports:
                embed_url = get_report_embed_url(report, metabase_service=metabase)
                data.append({
                    'id': report.id,
                    'transcription': report.transcription,
                    'status': report.status,
                    'created_at': report.created_at,
                    'created_by': report.created_by.email,
                    'chart_type': report.chart_type,
                    'row_count': report.row_count,
                    'execution_time_ms': report.execution_time_ms,
                    'sql': report.final_sql,
                    'embed_url': embed_url,
                    'metabase_question_id': report.metabase_question_id,
                    'can_edit': request.user.role == 'analyst'
                })
            logger.info(
                "Report list loaded for user=%s workspace=%s count=%s",
                request.user.id,
                workspace.id,
                len(data)
            )
            
            return Response({
                'success': True,
                'reports': data,
                'count': len(data)
            })
        
        except Exception as e:
            logger.error(f"Error in ReportListView: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ReportDetailView(APIView):
    """
    Get detailed report information.
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request, report_id):
        try:
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            report = get_object_or_404(
                VoiceReport,
                id=report_id,
                workspace=workspace
            )
            
            # TODO: Get history when ReportHistory model is added
            # history = ReportHistory.objects.filter(report=report).order_by('-timestamp')
            # history_data = [{
            #     'action': h.action,
            #     'performed_by': h.performed_by.email,
            #     'timestamp': h.timestamp,
            #     'changes': h.changes
            # } for h in history]
            history_data = []  # Placeholder until ReportHistory is added
            embed_url = get_report_embed_url(report)
            
            return Response({
                'success': True,
                'report': {
                    'id': report.id,
                    'transcription': report.transcription,
                    'intent': report.intent_json,
                    'generated_sql': report.generated_sql,
                    'final_sql': report.final_sql,
                    'status': report.status,
                    'sql_validated': report.sql_validated,
                    'sql_edited': report.sql_edited,
                    'query_result': report.query_result,
                    'row_count': report.row_count,
                    'execution_time_ms': report.execution_time_ms,
                    'chart_type': report.chart_type,
                    'metabase_question_id': report.metabase_question_id,
                    'metabase_dashboard_id': report.metabase_dashboard_id,
                    'embed_url': embed_url,
                    'error_message': report.error_message,
                    'created_at': report.created_at,
                    'created_by': report.created_by.email,
                    'edited_by': report.edited_by.email if report.edited_by else None,
                    'history': history_data
                }
            })
        
        except Exception as e:
            logger.error(f"Error in ReportDetailView: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def delete(self, request, report_id):
        """Delete report (Manager only)."""
        if request.user.role != 'manager':
            return Response(
                {'success': False, 'error': 'Only managers can delete reports'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            report = get_object_or_404(
                VoiceReport,
                id=report_id,
                workspace=workspace,
                created_by=request.user  # Can only delete own reports
            )
            
            report.delete()
            
            logger.info(f"Report {report_id} deleted by {request.user.email}")
            
            return Response({
                'success': True,
                'message': 'Report deleted successfully'
            })
        
        except Exception as e:
            logger.error(f"Error deleting report: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class WorkspaceDashboardView(APIView):
    """
    Get workspace dashboard for embedded viewing (Executive).
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get dashboard ID from any report
            report = VoiceReport.objects.filter(
                workspace=workspace,
                metabase_dashboard_id__isnull=False
            ).first()
            
            if not report:
                return Response({
                    'success': False,
                    'error': 'No dashboard available yet. Create some reports first.'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Generate fresh JWT embed URL for dashboard.
            metabase = get_metabase_service()
            embed_url = metabase.get_dashboard_embed_url(
                dashboard_id=report.metabase_dashboard_id
            )
            if not embed_url:
                return Response({
                    'success': False,
                    'error': metabase.last_error or 'Failed to generate dashboard embed URL'
                }, status=status.HTTP_502_BAD_GATEWAY)
            
            return Response({
                'success': True,
                'dashboard_url': embed_url,
                'dashboard_id': report.metabase_dashboard_id
            })
        
        except Exception as e:
            logger.error(f"Error in WorkspaceDashboardView: {e}", exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DashboardStatsView(APIView):
    """
    Return dashboard counters for the current user scope.
    """
    permission_classes = [IsAuthenticated]

    SUCCESS_STATUSES = (
        VoiceReport.STATUS_VISUALIZATION_CREATED,
        VoiceReport.STATUS_EXECUTED,
        VoiceReport.STATUS_COMPLETED,  # legacy
    )

    PROCESSING_STATUSES = (
        VoiceReport.STATUS_PENDING,
        VoiceReport.STATUS_PROCESSING,
        VoiceReport.STATUS_PENDING_EXECUTION,  # legacy
        VoiceReport.STATUS_EXECUTING,  # legacy
    )

    def get(self, request):
        try:
            workspace = get_user_workspace(request.user)
            if not workspace:
                return Response(
                    {'success': False, 'error': 'User must belong to a workspace'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            reports = VoiceReport.objects.filter(workspace=workspace)

            # Preserve list visibility semantics:
            # managers only see their own reports; others see workspace reports.
            if request.user.role == 'manager':
                reports = reports.filter(created_by=request.user)

            total_reports = reports.count()
            completed_reports = reports.filter(status__in=self.SUCCESS_STATUSES).count()
            failed_reports = reports.filter(status=VoiceReport.STATUS_FAILED).count()
            processing_reports = reports.filter(status__in=self.PROCESSING_STATUSES).count()
            total_rows = reports.aggregate(
                total_rows=Coalesce(Sum('row_count'), 0)
            )['total_rows']

            payload = {
                'success': True,
                'total_reports': total_reports,
                'completed_reports': completed_reports,
                'failed_reports': failed_reports,
                'processing_reports': processing_reports,
                'total_rows': int(total_rows or 0),
            }
            logger.info(
                "Dashboard stats loaded for user=%s workspace=%s payload=%s",
                request.user.id,
                workspace.id,
                payload
            )
            return Response(payload)
        except Exception as e:
            logger.error("Error in DashboardStatsView: %s", e, exc_info=True)
            return Response(
                {'success': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class HealthCheckView(APIView):
    """
    Health check for all services.
    """
    permission_classes = []  # Public endpoint
    
    def get(self, request):
        """Check connectivity to Small Whisper, ClickHouse, and Metabase."""
        health = {
            'small_whisper': False,
            'clickhouse': False,
            'metabase': False
        }
        
        # Check Small Whisper
        try:
            whisper_client = get_small_whisper_client()
            response = requests.get(f"{whisper_client.base_url}/health/", timeout=5)
            health['small_whisper'] = response.status_code == 200
        except:
            pass
        
        # Check ClickHouse
        try:
            executor = get_clickhouse_executor()
            health['clickhouse'] = executor.test_connection()
        except:
            pass
        
        # Check Metabase
        try:
            metabase = get_metabase_service()
            health['metabase'] = metabase.authenticate()
        except:
            pass
        
        all_healthy = all(health.values())
        
        return Response({
            'success': all_healthy,
            'services': health,
            'message': 'All services healthy' if all_healthy else 'Some services unavailable'
        }, status=status.HTTP_200_OK if all_healthy else status.HTTP_503_SERVICE_UNAVAILABLE)

