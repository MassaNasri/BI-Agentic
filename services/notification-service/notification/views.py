import logging

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import NotificationEventSerializer
from .services import (
    dispatch_subscription_expiry_warnings,
    is_internal_api_key_valid,
    process_event,
)

logger = logging.getLogger(__name__)


def _extract_internal_api_key(request):
    return request.headers.get('X-Internal-Api-Key') or request.META.get('HTTP_X_INTERNAL_API_KEY', '')


class NotificationHealthView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                'success': True,
                'service': 'notification-service',
            },
            status=status.HTTP_200_OK,
        )


class NotificationEventView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        request_key = _extract_internal_api_key(request)
        if not is_internal_api_key_valid(request_key):
            return Response(
                {
                    'success': False,
                    'message': 'Unauthorized internal notification request.',
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = NotificationEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        event_type = serializer.validated_data['event_type']
        event_key = serializer.validated_data.get('event_key', '')
        payload = serializer.validated_data.get('payload', {})

        try:
            counts = process_event(event_type=event_type, event_key=event_key, payload=payload)
        except ValueError as exc:
            return Response(
                {
                    'success': False,
                    'message': str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            logger.error("Notification event processing failed type=%s error=%s", event_type, exc, exc_info=True)
            return Response(
                {
                    'success': False,
                    'message': 'Internal notification processing failed.',
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        event_success = counts.get('failed', 0) == 0
        response_payload = {
            'success': event_success,
            'event_type': event_type,
            'result': counts,
        }
        if not event_success:
            response_payload['message'] = 'Notification dispatch completed with failures.'

        return Response(
            response_payload,
            status=status.HTTP_200_OK,
        )


class SubscriptionExpiryWarningRunView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        request_key = _extract_internal_api_key(request)
        if not is_internal_api_key_valid(request_key):
            return Response(
                {
                    'success': False,
                    'message': 'Unauthorized internal notification request.',
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            result = dispatch_subscription_expiry_warnings()
        except Exception as exc:
            logger.error("Subscription expiry warning run failed: %s", exc, exc_info=True)
            return Response(
                {
                    'success': False,
                    'message': 'Failed to run expiry warnings.',
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        run_success = result.get('failed', 0) == 0
        response_payload = {
            'success': run_success,
            'result': result,
        }
        if not run_success:
            response_payload['message'] = 'Expiry warning run completed with failures.'

        return Response(
            response_payload,
            status=status.HTTP_200_OK,
        )
