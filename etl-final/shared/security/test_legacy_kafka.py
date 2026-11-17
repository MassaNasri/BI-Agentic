"""A production source v1 replay window is explicit, short, and expires."""

from datetime import datetime, timedelta, timezone

from .legacy_kafka import allow_legacy_source_event


def test_source_v1_replay_is_disabled_by_default():
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)
    message = {"db_type": "postgresql"}
    assert not allow_legacy_source_event(message, environment={"APP_ENV": "production"}, now=now)
    assert not allow_legacy_source_event(message, environment={
        "APP_ENV": "production", "KAFKA_V1_SOURCE_REPLAY_UNTIL": "2030-01-01T00:00:00Z",
    }, now=now)
    assert allow_legacy_source_event(message, environment={
        "APP_ENV": "production", "KAFKA_V1_SOURCE_REPLAY_UNTIL": (now + timedelta(days=2)).isoformat(),
    }, now=now)
    assert not allow_legacy_source_event(message, environment={
        "APP_ENV": "production", "KAFKA_V1_SOURCE_REPLAY_UNTIL": (now - timedelta(seconds=1)).isoformat(),
    }, now=now)
    assert allow_legacy_source_event({"db_type": "sqlite"}, environment={"APP_ENV": "production"}, now=now)
