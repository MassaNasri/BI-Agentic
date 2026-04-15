from __future__ import annotations

import logging
import re
from typing import Callable

import requests

from preprocessing_low.error_handler import (
    PreprocessInfrastructureError,
    PreprocessModelOutputError,
    PreprocessTimeoutError,
)
from preprocessing_low.schemas import TextPreprocessConfig


_MEANINGLESS_OUTPUTS = {"__empty__", "empty", "n/a", "na", "none", "null"}


def _build_preprocess_prompt(raw_text: str) -> str:
    return (
        "You are a multilingual text preprocessing engine for speech transcripts.\n"
        "Rewrite noisy transcription into a concise intent-focused query for intent classification.\n\n"
        "Rules:\n"
        "1) Keep only meaningful analytical/query intent.\n"
        "2) Remove filler words, greetings, conversational phrases, hesitation sounds, speech artifacts, repeated text, malformed symbols, and redundant punctuation.\n"
        "3) Preserve entities, metrics, dimensions, filters, numbers, dates, and comparison terms.\n"
        "4) Keep the original language of the user's intent whenever possible.\n"
        "5) If no meaningful query intent exists, output exactly __EMPTY__.\n\n"
        "Output constraints:\n"
        "- Output only the cleaned text.\n"
        "- No explanation.\n"
        "- No comments.\n"
        "- No markdown.\n"
        "- No surrounding quotes.\n\n"
        f"Input:\n{raw_text}\n\n"
        "Output:"
    )


def _is_meaningful_cleaned_output(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", (text or "")).strip()
    if not normalized:
        return False

    if normalized.lower() in _MEANINGLESS_OUTPUTS:
        return False

    if not re.search(r"\w", normalized, flags=re.UNICODE):
        return False

    compact = re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)
    return len(compact) >= 2


def _extract_ollama_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error_value = payload.get("error")
            if isinstance(error_value, str) and error_value.strip():
                return error_value.strip()
    except ValueError:
        pass
    return response.text.strip()


def _call_ollama_preprocessor(
    text: str,
    config: TextPreprocessConfig,
    logger: logging.Logger,
    log_event: Callable[[logging.Logger, int, str], None] | Callable[..., None],
) -> str:
    prompt = _build_preprocess_prompt(text)
    payload = {
        "model": config.ollama_model,
        "prompt": prompt,
        "stream": False,
    }

    log_event(
        logger,
        logging.INFO,
        "Calling Ollama text preprocessor",
        model=config.ollama_model,
        endpoint=config.ollama_url,
        input_chars=len(text),
    )

    try:
        response = requests.post(
            config.ollama_url,
            json=payload,
            timeout=config.request_timeout_seconds,
        )
    except requests.Timeout as exc:
        raise PreprocessTimeoutError(
            f"Ollama request timed out after {config.request_timeout_seconds}s."
        ) from exc
    except requests.ConnectionError as exc:
        raise PreprocessInfrastructureError(f"Ollama unavailable: {exc}") from exc
    except requests.RequestException as exc:
        raise PreprocessInfrastructureError(f"Ollama request failed: {exc}") from exc

    if response.status_code in {408, 504}:
        raise PreprocessTimeoutError(
            f"Ollama returned timeout HTTP {response.status_code}: {_extract_ollama_error_message(response)}"
        )

    if response.status_code >= 400:
        error_message = _extract_ollama_error_message(response)
        raise PreprocessInfrastructureError(
            f"Ollama returned HTTP {response.status_code}: {error_message}"
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise PreprocessModelOutputError("Ollama returned a non-JSON response.") from exc

    model_output = str(body.get("response", "")).strip()
    if not _is_meaningful_cleaned_output(model_output):
        raise PreprocessModelOutputError(
            f"Model output is empty or meaningless: {model_output!r}"
        )

    normalized_output = re.sub(r"\s+", " ", model_output).strip()
    log_event(
        logger,
        logging.INFO,
        "Ollama text preprocessing completed",
        output_chars=len(normalized_output),
    )
    return normalized_output
