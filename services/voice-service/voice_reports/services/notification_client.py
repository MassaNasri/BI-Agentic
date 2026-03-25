import logging
import os

import requests

logger = logging.getLogger(__name__)


class NotificationClient:
    def __init__(self):
        self.base_url = os.getenv('NOTIFICATION_SERVICE_URL', 'http://notification-service:8010').rstrip('/')
        self.api_key = os.getenv('NOTIFICATION_SERVICE_API_KEY', '').strip()
        self.events_endpoint = f'{self.base_url}/notification/events/'

    def send_event(self, *, event_type, payload, event_key=''):
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['X-Internal-Api-Key'] = self.api_key

        request_body = {
            'event_type': event_type,
            'event_key': event_key,
            'payload': payload,
        }
        try:
            response = requests.post(
                self.events_endpoint,
                json=request_body,
                headers=headers,
                timeout=(5, 15),
            )
        except requests.RequestException as exc:
            logger.error(
                'Notification service request failed event_type=%s key=%s error=%s',
                event_type,
                event_key,
                exc,
            )
            return {'success': False, 'error': str(exc)}

        if response.status_code != 200:
            logger.error(
                'Notification service returned non-200 event_type=%s key=%s status=%s body=%s',
                event_type,
                event_key,
                response.status_code,
                response.text[:500],
            )
            return {'success': False, 'error': f'http_{response.status_code}'}

        try:
            payload = response.json()
        except ValueError:
            payload = {'success': False}

        if not payload.get('success'):
            return {'success': False, 'error': payload.get('message', 'notification_event_failed')}

        return {'success': True, 'data': payload}


_notification_client = None


def get_notification_client():
    global _notification_client
    if _notification_client is None:
        _notification_client = NotificationClient()
    return _notification_client
