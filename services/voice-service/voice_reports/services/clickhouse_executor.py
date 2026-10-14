"""Result sanitization helpers.

Foundation-A deliberately removed every Voice-side ClickHouse client and
executor. Analytical execution belongs exclusively to query-service.
"""

from __future__ import annotations

from decimal import Decimal
import math
from typing import Any


def sanitize_numeric_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bytes, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        try:
            value = float(value)
        except (ValueError, OverflowError):
            return 0
    if isinstance(value, float):
        return 0 if math.isnan(value) or math.isinf(value) else value
    try:  # numpy is optional and only used when already installed.
        import numpy as np

        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            normalized = float(value)
            return 0 if math.isnan(normalized) or math.isinf(normalized) else normalized
    except (ImportError, TypeError, ValueError, OverflowError):
        pass
    return value


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value]
    return sanitize_numeric_value(value)


def sanitize_query_results(rows: list[dict]) -> list[dict]:
    return [
        {key: _sanitize_value(value) for key, value in row.items()}
        for row in rows
        if isinstance(row, dict)
    ]


__all__ = ["sanitize_numeric_value", "sanitize_query_results"]
