import logging
import os
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'service_config.settings')

import django  # noqa: E402
django.setup()
from django.test import override_settings  # noqa: E402

from database.utils import ClickHouseClient, quote_clickhouse_identifier  # noqa: E402


@override_settings(
    CLICKHOUSE_HOST='clickhouse', CLICKHOUSE_PORT='8123',
    CLICKHOUSE_USER='service-user', CLICKHOUSE_PASSWORD='do-not-log-this',
)
def test_clickhouse_auth_is_not_sent_in_url_or_query_params():
    with patch('database.utils.requests.post') as post:
        post.return_value.text = '1'
        post.return_value.raise_for_status.return_value = None
        ClickHouseClient().execute_query('SELECT 1')
    _, kwargs = post.call_args
    assert 'params' not in kwargs
    assert kwargs['auth'] == ('service-user', 'do-not-log-this')
    assert 'do-not-log-this' not in post.call_args.args[0]


@override_settings(CLICKHOUSE_PASSWORD='do-not-log-this')
def test_request_exception_is_redacted_from_logs(caplog):
    with patch('database.utils.requests.post', side_effect=RuntimeError('url?password=do-not-log-this')):
        with caplog.at_level(logging.ERROR):
            result = ClickHouseClient().execute_query('SELECT 1')
    assert result['success'] is False
    assert 'do-not-log-this' not in caplog.text
    assert 'do-not-log-this' not in result['error']


def test_malicious_identifiers_are_rejected():
    for value in ['bad; DROP TABLE x', 'system.tables', 'a`b', '', '../x']:
        with pytest.raises(ValueError):
            quote_clickhouse_identifier(value)
