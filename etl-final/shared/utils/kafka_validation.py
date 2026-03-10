"""
Shared Kafka message validation helpers.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

from .kafka_schema_validator import KafkaSchemaValidator


def _is_truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def validate_message(topic: str, message: Dict[str, Any], validate_messages: bool = True) -> Tuple[bool, Optional[str]]:
    """
    Validate a Kafka message against the topic schema.

    If schema validation crashes and KAFKA_VALIDATION_FAIL_OPEN is enabled,
    the message is allowed through.
    """
    if not validate_messages:
        return True, None

    try:
        is_valid, error = KafkaSchemaValidator.validate_message(topic, message)
        if not is_valid:
            return False, error
        return True, None
    except Exception as exc:
        fail_open = _is_truthy(os.getenv("KAFKA_VALIDATION_FAIL_OPEN", "false"))
        if fail_open:
            logging.getLogger(__name__).warning(
                "[Kafka Validation] Validator failed for topic=%s but fail-open is enabled: %s",
                topic,
                exc,
            )
            return True, None
        return False, str(exc)

