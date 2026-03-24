from typing import Any


def make_error(
    code: str,
    message: str,
    *,
    stage: str,
    details: dict[str, Any] | None = None,
    retryable: bool = False,
) -> dict[str, Any]:
    return {
        "error": True,
        "error_code": code,
        "message": message,
        "stage": stage,
        "retryable": retryable,
        "details": details or {},
    }
