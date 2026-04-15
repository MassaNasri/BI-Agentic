from __future__ import annotations

import requests

from preprocessing_low.schemas import PreprocessActionType, PreprocessErrorType, TextPreprocessConfig


class PreprocessError(Exception):
    """Base exception for text preprocessing failures."""


class PreprocessInputError(PreprocessError):
    """Invalid text input for preprocessing."""


class PreprocessModelOutputError(PreprocessError):
    """Invalid or meaningless model output."""


class PreprocessInfrastructureError(PreprocessError):
    """Unavailable Ollama runtime or networking dependency."""


class PreprocessTimeoutError(PreprocessError):
    """Ollama inference timed out."""


def classify_preprocess_error(exception: BaseException) -> PreprocessErrorType:
    if isinstance(exception, PreprocessInputError):
        return "input"

    if isinstance(exception, PreprocessInfrastructureError):
        return "infra"

    if isinstance(exception, (PreprocessTimeoutError, requests.Timeout)):
        return "system"

    if isinstance(exception, PreprocessModelOutputError):
        return "model"

    if isinstance(exception, requests.ConnectionError):
        return "infra"

    if isinstance(exception, requests.RequestException):
        message = str(exception).lower()
        if "timeout" in message or "timed out" in message:
            return "system"
        if "connection" in message or "refused" in message:
            return "infra"
        return "unknown"

    message = str(exception).lower()
    if "timeout" in message or "timed out" in message:
        return "system"
    return "unknown"


def _decide_preprocess_action(
    error_type: PreprocessErrorType,
    retry_count: int,
    config: TextPreprocessConfig,
) -> PreprocessActionType:
    if error_type in {"system", "model"} and retry_count < config.max_retries:
        return "retry"
    return "stop"
