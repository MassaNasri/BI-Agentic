from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, TypedDict


PreprocessErrorType = Literal["system", "input", "model", "infra", "unknown"]
PreprocessActionType = Literal["retry", "stop"]


class PreprocessResult(TypedDict):
    status: Literal["success", "failed", "degraded"]
    cleaned_text: str
    error_type: str
    action_taken: PreprocessActionType
    degraded: bool
    degradation_reason: str
    confidence: float
    detected_changes: list[dict[str, str]]
    warnings: list[dict[str, str]]
    errors: list[dict[str, str]]
    debug_metadata: dict[str, object]
    attempts: list[dict[str, object]]
    attempts_count: int
    started_at: str
    finished_at: str
    duration_ms: int


def _env_float(name: str, default: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default


@dataclass(frozen=True)
class TextPreprocessConfig:
    ollama_url: str
    ollama_model: str
    request_timeout_seconds: float
    max_retries: int

    @classmethod
    def from_env(cls) -> "TextPreprocessConfig":
        return cls(
            ollama_url=os.getenv("TEXT_PREPROCESS_OLLAMA_URL", "http://localhost:11434/api/generate"),
            ollama_model=os.getenv("TEXT_PREPROCESS_MODEL", "gemma3:1b"),
            request_timeout_seconds=_env_float("TEXT_PREPROCESS_TIMEOUT_SECONDS", 20.0),
            max_retries=1,
        )


def build_preprocess_success_result(cleaned_text: str) -> PreprocessResult:
    return {
        "status": "success",
        "cleaned_text": cleaned_text,
        "error_type": "none",
        "action_taken": "stop",
        "degraded": False,
        "degradation_reason": "",
        "confidence": 0.0,
        "detected_changes": [],
        "warnings": [],
        "errors": [],
        "debug_metadata": {},
        "attempts": [],
        "attempts_count": 0,
        "started_at": "",
        "finished_at": "",
        "duration_ms": 0,
    }


def build_preprocess_failed_result(
    error_type: PreprocessErrorType,
    action_taken: PreprocessActionType,
) -> PreprocessResult:
    return {
        "status": "failed",
        "cleaned_text": "",
        "error_type": error_type,
        "action_taken": action_taken,
        "degraded": False,
        "degradation_reason": "",
        "confidence": 0.0,
        "detected_changes": [],
        "warnings": [],
        "errors": [],
        "debug_metadata": {},
        "attempts": [],
        "attempts_count": 0,
        "started_at": "",
        "finished_at": "",
        "duration_ms": 0,
    }
