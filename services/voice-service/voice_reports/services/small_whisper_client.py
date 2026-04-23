"""
Small Whisper client.

Calls the AI transcription service as a black box.
"""

import logging
import os
import re
from typing import Dict

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


_EXPLICIT_NON_ANALYTICAL_TYPES = {
    "conversational",
    "informational",
    "invalid_input",
    "numeric_only_input",
    "noise_input",
    "empty_input",
    "transcription_failure",
    "no_speech_detected",
}
_ANALYTICAL_TYPES = {"analytical", "predictive", "forecast", "forecasting"}
_ANALYTICAL_FALLBACK_PATTERNS = (
    r"\b(show|list|give|display)\b.*\b(total|sum|average|avg|count|max|min|distribution|breakdown|population|revenue|profit|margin)\b",
    r"\b(total|sum|average|avg|count|max|min|distribution|breakdown)\b.*\b(by|per|across|for each|in each)\b",
    r"\b(top|bottom)\s+\d+\b.*\bby\b",
    r"\bhow many\b.*\b(by|per|across|for each|in each)\b",
)
_CONVERSATIONAL_PATTERNS = (
    r"\bhello\b",
    r"\bhi\b",
    r"\bhey\b",
    r"\bhow are you\b",
    r"\bthank(s| you)\b",
)


def _normalize_question_type(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"information", "informational", "info", "non_analytical", "non-analytical"}:
        return "conversational"
    return normalized or "unknown"


def _looks_analytical_question(question: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(question or "").lower()).strip()
    if not normalized:
        return False
    return any(re.search(pattern, normalized) for pattern in _ANALYTICAL_FALLBACK_PATTERNS)


def _looks_conversational_question(question: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(question or "").lower()).strip()
    if not normalized:
        return False
    return any(re.search(pattern, normalized) for pattern in _CONVERSATIONAL_PATTERNS)


def _extract_failed_text_classification(llm_payload: dict, question: str) -> tuple[str, str, bool]:
    details = llm_payload.get("details", {}) if isinstance(llm_payload.get("details"), dict) else {}
    trace = llm_payload.get("pipeline_trace", {}) if isinstance(llm_payload.get("pipeline_trace"), dict) else {}
    trace_input = trace.get("input_validation", {}) if isinstance(trace.get("input_validation"), dict) else {}
    trace_final = trace_input.get("final_output", {}) if isinstance(trace_input.get("final_output"), dict) else {}
    details_intent = details.get("intent", {}) if isinstance(details.get("intent"), dict) else {}
    details_trace = details.get("pipeline_trace", {}) if isinstance(details.get("pipeline_trace"), dict) else {}
    details_trace_input = (
        details_trace.get("input_validation", {})
        if isinstance(details_trace.get("input_validation"), dict)
        else {}
    )
    details_trace_final = (
        details_trace_input.get("final_output", {})
        if isinstance(details_trace_input.get("final_output"), dict)
        else {}
    )
    overall_status = llm_payload.get("overall_status", {}) if isinstance(llm_payload.get("overall_status"), dict) else {}
    details_overall_status = details.get("overall_status", {}) if isinstance(details.get("overall_status"), dict) else {}

    classification_candidates = [
        llm_payload.get("question_type"),
        details_intent.get("classification"),
        details_intent.get("question_type"),
        trace_final.get("classification"),
        trace_final.get("question_type"),
        details_trace_final.get("classification"),
        details_trace_final.get("question_type"),
        llm_payload.get("final_route"),
        overall_status.get("final_route"),
        details.get("final_route"),
        details_overall_status.get("final_route"),
    ]

    classification = "unknown"
    for candidate in classification_candidates:
        normalized = _normalize_question_type(candidate)
        if normalized in _ANALYTICAL_TYPES or normalized in _EXPLICIT_NON_ANALYTICAL_TYPES:
            classification = normalized
            break

    if classification == "unknown":
        if _looks_analytical_question(question):
            classification = "analytical"
        elif _looks_conversational_question(question):
            classification = "conversational"

    classification_reason = (
        details_intent.get("classification_reason")
        or trace_final.get("reason")
        or details_trace_final.get("reason")
        or llm_payload.get("message")
        or details.get("message")
        or "Pipeline returned a non-success response."
    )
    needs_sql = classification in _ANALYTICAL_TYPES
    return classification, str(classification_reason), bool(needs_sql)


class SmallWhisperClient:
    """
    Client for calling Small Whisper service.
    Treats it as a black box API and handles both analytical and conversational responses.
    """

    def __init__(self):
        self.base_url = getattr(settings, "SMALL_WHISPER_URL", "http://127.0.0.1:8001")
        self.transcribe_endpoint = f"{self.base_url}/api/transcribe/"
        self.reasoning_endpoint = f"{self.base_url}/api/reasoning/test/"
        self.intent_endpoint = f"{self.base_url}/api/llm/intent/"
        self.health_endpoint = f"{self.base_url}/admin/"

        self.health_timeout_seconds = int(
            getattr(settings, "SMALL_WHISPER_HEALTH_TIMEOUT_SECONDS", 5)
        )
        self.connect_timeout_seconds = int(
            getattr(settings, "SMALL_WHISPER_CONNECT_TIMEOUT_SECONDS", 10)
        )
        self.read_timeout_seconds = int(
            getattr(settings, "SMALL_WHISPER_TIMEOUT_SECONDS", 300)
        )
        self.max_retries = max(
            0,
            int(getattr(settings, "SMALL_WHISPER_MAX_RETRIES", 1)),
        )
        self.internal_api_key = str(getattr(settings, "AI_SERVICE_INTERNAL_API_KEY", "") or "").strip()

        logger.info(
            "Small Whisper Client initialized base_url=%s timeout=(%ss connect, %ss read) retries=%s",
            self.base_url,
            self.connect_timeout_seconds,
            self.read_timeout_seconds,
            self.max_retries,
        )

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.internal_api_key:
            headers["X-Internal-Api-Key"] = self.internal_api_key
        return headers

    def check_health(self) -> bool:
        try:
            response = requests.get(self.health_endpoint, timeout=self.health_timeout_seconds)
            return response.status_code in [200, 301, 302, 404]
        except requests.exceptions.RequestException as exc:
            logger.error("Health check failed for %s: %s", self.base_url, exc)
            return False

    def _prepare_files(self, audio_file):
        """
        Build multipart payload and optional file handle that must be closed by caller.
        """
        if hasattr(audio_file, "read"):
            audio_file.seek(0)
            filename = getattr(audio_file, "name", "audio.wav")
            return {"audio": (filename, audio_file, "audio/wav")}, None

        file_handle = open(audio_file, "rb")
        filename = os.path.basename(audio_file)
        return {"audio": (filename, file_handle, "audio/wav")}, file_handle

    def process_audio(
        self,
        audio_file,
        user_id: str | None = None,
        *,
        workspace_id: str | None = None,
        manager_id: str | None = None,
        dataset_id: str | None = None,
        source_id: str | None = None,
        table_name: str | None = None,
        report_id: str | None = None,
    ) -> Dict:
        logger.info("Starting Small Whisper request endpoint=%s", self.transcribe_endpoint)

        if not self.check_health():
            error_msg = (
                f"Small Whisper service is not reachable at {self.base_url}. "
                "Please ensure the ai-service container is healthy."
            )
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

        attempts = self.max_retries + 1
        for attempt in range(1, attempts + 1):
            file_to_close = None
            try:
                files, file_to_close = self._prepare_files(audio_file)
                form_data = {}
                if user_id is not None and str(user_id).strip():
                    form_data["user_id"] = str(user_id).strip()
                if manager_id is not None and str(manager_id).strip():
                    form_data["manager_id"] = str(manager_id).strip()
                if workspace_id is not None and str(workspace_id).strip():
                    form_data["workspace_id"] = str(workspace_id).strip()
                if dataset_id is not None and str(dataset_id).strip():
                    form_data["dataset_id"] = str(dataset_id).strip()
                if source_id is not None and str(source_id).strip():
                    form_data["source_id"] = str(source_id).strip()
                if table_name is not None and str(table_name).strip():
                    form_data["table_name"] = str(table_name).strip()
                if report_id is not None and str(report_id).strip():
                    form_data["report_id"] = str(report_id).strip()

                response = requests.post(
                    self.transcribe_endpoint,
                    files=files,
                    data=form_data or None,
                    headers=self._headers(),
                    timeout=(self.connect_timeout_seconds, self.read_timeout_seconds),
                )

                logger.info(
                    "Small Whisper response status=%s attempt=%s/%s",
                    response.status_code,
                    attempt,
                    attempts,
                )

                if response.status_code != 200:
                    error_detail = response.text[:500]
                    logger.error(
                        "Small Whisper returned non-200 status=%s body=%s",
                        response.status_code,
                        error_detail,
                    )
                    return {
                        "success": False,
                        "error": f"Small Whisper returned {response.status_code}: {error_detail}",
                    }

                try:
                    result = response.json()
                except ValueError:
                    logger.error("Small Whisper returned non-JSON body: %s", response.text[:500])
                    return {
                        "success": False,
                        "error": "Small Whisper returned invalid JSON response",
                    }

                if not isinstance(result, dict):
                    return {
                        "success": False,
                        "error": "Small Whisper returned invalid response payload",
                    }

                text = result.get("text", "")
                reasoning = result.get("reasoning", {})
                llm_data = result.get("llm")
                preprocessing_low = result.get("preprocessing_low")
                preprocessing_high = result.get("preprocessing_high")
                pipeline_trace = result.get("pipeline_trace")
                overall_status = result.get("overall_status")
                root_cause = result.get("root_cause")
                dagster_runtime = result.get("dagster_runtime")
                final_route = result.get("final_route")
                final_user_message = result.get("final_user_message")

                question_type = _normalize_question_type(reasoning.get("question_type", "unknown"))
                if question_type == "unknown":
                    if _looks_analytical_question(text):
                        question_type = "analytical"
                    elif _looks_conversational_question(text):
                        question_type = "conversational"
                needs_sql = bool(reasoning.get("needs_sql", False) or question_type in _ANALYTICAL_TYPES)
                is_explicit_non_analytical = question_type in _EXPLICIT_NON_ANALYTICAL_TYPES

                if is_explicit_non_analytical:
                    return {
                        "success": True,
                        "text": text,
                        "reasoning": reasoning,
                        "question_type": question_type,
                        "intent": None,
                        "sql": None,
                        "chart": None,
                        "message": reasoning.get(
                            "message", "Question does not require data analysis"
                        ),
                        "preprocessing_low": preprocessing_low,
                        "preprocessing_high": preprocessing_high,
                        "pipeline_trace": pipeline_trace,
                        "overall_status": overall_status,
                        "root_cause": root_cause,
                        "dagster_runtime": dagster_runtime,
                        "final_route": final_route,
                        "final_user_message": final_user_message,
                        "confidence": result.get("confidence"),
                        "confidence_breakdown": result.get("confidence_breakdown"),
                        "degraded": result.get("degraded"),
                        "raw_response": result,
                    }

                if question_type not in _ANALYTICAL_TYPES and not needs_sql:
                    return {
                        "success": True,
                        "text": text,
                        "reasoning": reasoning,
                        "question_type": question_type,
                        "intent": None,
                        "sql": None,
                        "chart": None,
                        "message": (
                            str(final_user_message or "").strip()
                            or reasoning.get("message")
                            or "Pipeline could not confidently classify the request."
                        ),
                        "preprocessing_low": preprocessing_low,
                        "preprocessing_high": preprocessing_high,
                        "pipeline_trace": pipeline_trace,
                        "overall_status": overall_status,
                        "root_cause": root_cause,
                        "dagster_runtime": dagster_runtime,
                        "final_route": final_route,
                        "final_user_message": final_user_message,
                        "confidence": result.get("confidence"),
                        "confidence_breakdown": result.get("confidence_breakdown"),
                        "degraded": result.get("degraded"),
                        "raw_response": result,
                    }

                if not llm_data or not isinstance(llm_data, dict):
                    message = reasoning.get("message", "Analytical stage failed")
                    return {
                        "success": True,
                        "text": text,
                        "reasoning": reasoning,
                        "question_type": question_type,
                        "intent": None,
                        "sql": None,
                        "chart": None,
                        "message": message,
                        "analytical_error": reasoning.get("analytical_error"),
                        "preprocessing_low": preprocessing_low,
                        "preprocessing_high": preprocessing_high,
                        "pipeline_trace": pipeline_trace,
                        "overall_status": overall_status,
                        "root_cause": root_cause,
                        "dagster_runtime": dagster_runtime,
                        "final_route": final_route,
                        "final_user_message": final_user_message,
                        "confidence": result.get("confidence"),
                        "confidence_breakdown": result.get("confidence_breakdown"),
                        "degraded": result.get("degraded"),
                        "raw_response": result,
                    }

                return {
                    "success": True,
                    "text": text,
                    "reasoning": reasoning,
                    "question_type": question_type,
                    "intent": llm_data.get("intent"),
                    "sql": llm_data.get("sql"),
                    "generated_sql": llm_data.get("generated_sql"),
                    "reviewed_sql": llm_data.get("reviewed_sql"),
                    "sql_review": llm_data.get("sql_review"),
                    "chart": llm_data.get("chart"),
                    "confidence": result.get("confidence", llm_data.get("confidence", 0.5)),
                    "confidence_breakdown": result.get("confidence_breakdown") or llm_data.get("confidence_breakdown"),
                    "degraded": result.get("degraded"),
                    "preprocessing_low": preprocessing_low,
                    "preprocessing_high": preprocessing_high,
                    "pipeline_trace": pipeline_trace,
                    "overall_status": overall_status,
                    "root_cause": root_cause,
                    "dagster_runtime": dagster_runtime,
                    "final_route": final_route,
                    "final_user_message": final_user_message,
                    "raw_response": result,
                }

            except requests.exceptions.Timeout as exc:
                logger.warning(
                    "Small Whisper timeout attempt=%s/%s after %ss read timeout: %s",
                    attempt,
                    attempts,
                    self.read_timeout_seconds,
                    exc,
                )
                if attempt >= attempts:
                    break
            except requests.exceptions.ConnectionError as exc:
                logger.error("Cannot connect to Small Whisper endpoint=%s error=%s", self.transcribe_endpoint, exc)
                return {
                    "success": False,
                    "error": (
                        f"Small Whisper service is not reachable at {self.base_url}. "
                        "Verify the ai-service container and DNS connectivity."
                    ),
                }
            except Exception as exc:
                logger.exception("Unexpected error while calling Small Whisper")
                return {"success": False, "error": f"Unexpected error: {exc}"}
            finally:
                if file_to_close:
                    file_to_close.close()

        timeout_error = (
            f"Small Whisper processing timed out after {self.read_timeout_seconds} seconds. "
            "Try again with a shorter audio file or switch to a smaller Whisper model."
        )
        logger.error(timeout_error)
        return {"success": False, "error": timeout_error}

    def process_text(
        self,
        text: str,
        user_id: str | None = None,
        *,
        workspace_id: str | None = None,
        manager_id: str | None = None,
        dataset_id: str | None = None,
        source_id: str | None = None,
        table_name: str | None = None,
        report_id: str | None = None,
    ) -> Dict:
        """
        Process text directly through the full AI pipeline endpoint.
        This ensures analyst-visible traceability for all classes, including
        invalid/conversational/non-analytical requests.
        """
        question = (text or "").strip()
        if not question:
            return {"success": False, "error": "Text is required"}

        logger.info("Starting text pipeline endpoint=%s", self.intent_endpoint)

        if not self.check_health():
            error_msg = (
                f"Small Whisper service is not reachable at {self.base_url}. "
                "Please ensure the ai-service container is healthy."
            )
            logger.error(error_msg)
            return {"success": False, "error": error_msg}

        try:
            llm_payload = {"question": question}
            if user_id is not None and str(user_id).strip():
                llm_payload["user_id"] = str(user_id).strip()
            if manager_id is not None and str(manager_id).strip():
                llm_payload["manager_id"] = str(manager_id).strip()
            if workspace_id is not None and str(workspace_id).strip():
                llm_payload["workspace_id"] = str(workspace_id).strip()
            if dataset_id is not None and str(dataset_id).strip():
                llm_payload["dataset_id"] = str(dataset_id).strip()
            if source_id is not None and str(source_id).strip():
                llm_payload["source_id"] = str(source_id).strip()
            if table_name is not None and str(table_name).strip():
                llm_payload["table_name"] = str(table_name).strip()
            if report_id is not None and str(report_id).strip():
                llm_payload["report_id"] = str(report_id).strip()

            llm_response = requests.post(
                self.intent_endpoint,
                json=llm_payload,
                headers=self._headers(),
                timeout=(self.connect_timeout_seconds, self.read_timeout_seconds),
            )

            try:
                llm_payload = llm_response.json()
            except ValueError:
                return {
                    "success": False,
                    "error": "Intent endpoint returned invalid JSON response",
                }

            if not isinstance(llm_payload, dict):
                return {
                    "success": False,
                    "error": "Intent endpoint returned invalid response payload",
                }

            if llm_response.status_code != 200 or llm_payload.get("error"):
                classification, classification_reason, needs_sql = _extract_failed_text_classification(
                    llm_payload=llm_payload,
                    question=question,
                )
                reasoning = {
                    "question_type": classification,
                    "needs_sql": bool(needs_sql),
                    "needs_chart": bool(needs_sql),
                    "message": classification_reason or "Question does not require data analysis",
                }
                return {
                    "success": True,
                    "text": question,
                    "reasoning": reasoning,
                    "question_type": classification,
                    "intent": None,
                    "sql": None,
                    "chart": None,
                    "message": reasoning["message"],
                    "analytical_error": llm_payload,
                    "preprocessing_low": llm_payload.get("preprocessing_low"),
                    "preprocessing_high": llm_payload.get("preprocessing_high"),
                    "pipeline_trace": llm_payload.get("pipeline_trace"),
                    "overall_status": llm_payload.get("overall_status"),
                    "root_cause": llm_payload.get("root_cause"),
                    "dagster_runtime": llm_payload.get("dagster_runtime"),
                    "final_route": llm_payload.get("final_route"),
                    "final_user_message": llm_payload.get("final_user_message"),
                    "confidence": llm_payload.get("confidence"),
                    "confidence_breakdown": llm_payload.get("confidence_breakdown"),
                    "degraded": llm_payload.get("degraded"),
                    "raw_response": {"llm": llm_payload},
                }

            question_type = _normalize_question_type(
                llm_payload.get("question_type")
                or (
                    llm_payload.get("intent", {}).get("question_type")
                    if isinstance(llm_payload.get("intent"), dict)
                    else None
                )
            )
            if question_type == "unknown":
                if str(llm_payload.get("final_route", "")).strip().lower() == "forecasting":
                    question_type = "predictive"
                elif llm_payload.get("sql"):
                    question_type = "analytical"
                else:
                    question_type = "analytical" if _looks_analytical_question(question) else "conversational"
            reasoning = {
                "question_type": question_type,
                "needs_sql": bool(question_type in _ANALYTICAL_TYPES),
                "needs_chart": bool(question_type in _ANALYTICAL_TYPES),
                "message": llm_payload.get("final_user_message", "Analytical request processed."),
            }
            return {
                "success": True,
                "text": question,
                "reasoning": reasoning,
                "question_type": question_type,
                "intent": llm_payload.get("intent"),
                "sql": llm_payload.get("sql"),
                "generated_sql": llm_payload.get("generated_sql"),
                "reviewed_sql": llm_payload.get("reviewed_sql"),
                "sql_review": llm_payload.get("sql_review"),
                "chart": llm_payload.get("chart"),
                "confidence": llm_payload.get("confidence", 0.5),
                "confidence_breakdown": llm_payload.get("confidence_breakdown"),
                "degraded": llm_payload.get("degraded"),
                "preprocessing_low": llm_payload.get("preprocessing_low"),
                "preprocessing_high": llm_payload.get("preprocessing_high"),
                "pipeline_trace": llm_payload.get("pipeline_trace"),
                "overall_status": llm_payload.get("overall_status"),
                "root_cause": llm_payload.get("root_cause"),
                "dagster_runtime": llm_payload.get("dagster_runtime"),
                "final_route": llm_payload.get("final_route"),
                "final_user_message": llm_payload.get("final_user_message"),
                "raw_response": {"llm": llm_payload},
            }

        except requests.exceptions.Timeout as exc:
            error_msg = (
                f"Text processing timed out after {self.read_timeout_seconds} seconds. "
                "Please try again."
            )
            logger.error("%s Error=%s", error_msg, exc)
            return {"success": False, "error": error_msg}
        except requests.exceptions.ConnectionError as exc:
            logger.error("Cannot connect to text pipeline endpoints error=%s", exc)
            return {
                "success": False,
                "error": (
                    f"Small Whisper service is not reachable at {self.base_url}. "
                    "Verify the ai-service container and DNS connectivity."
                ),
            }
        except Exception as exc:
            logger.exception("Unexpected error while processing text")
            return {"success": False, "error": f"Unexpected error: {exc}"}


_small_whisper_client = None


def get_small_whisper_client() -> SmallWhisperClient:
    global _small_whisper_client
    if _small_whisper_client is None:
        _small_whisper_client = SmallWhisperClient()
    return _small_whisper_client
