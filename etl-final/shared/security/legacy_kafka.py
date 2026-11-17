"""Bounded compatibility for pre-cutover source events on retained Kafka topics."""

import os
from datetime import datetime, timedelta, timezone


def allow_legacy_source_event(message, *, environment=None, now=None):
    environment = os.environ if environment is None else environment
    if str(message.get("db_type", "")).lower() in {"sqlite", "sqlite3"}:
        return True  # File-token snapshots do not carry source passwords.
    if environment.get("APP_ENV") != "production":
        return True
    deadline_text = environment.get("KAFKA_V1_SOURCE_REPLAY_UNTIL", "")
    if not deadline_text:
        return False
    now = datetime.now(timezone.utc) if now is None else now
    try:
        deadline = datetime.fromisoformat(deadline_text.replace("Z", "+00:00"))
    except ValueError:
        return False
    if deadline.tzinfo is None:
        return False
    return now < deadline <= now + timedelta(days=7)
