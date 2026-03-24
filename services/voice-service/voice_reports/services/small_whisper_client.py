"""
Small Whisper client.

Calls the AI transcription service as a black box.
"""

import logging
import os
from typing import Dict

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class SmallWhisperClient:
    """
    Client for calling Small Whisper service.
    Treats it as a black box API and handles both analytical and conversational responses.
    """

    def __init__(self):
        self.base_url = getattr(settings, "SMALL_WHISPER_URL", "http://127.0.0.1:8001")
        self.transcribe_endpoint = f"{self.base_url}/api/transcribe/"
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

        logger.info(
            "Small Whisper Client initialized base_url=%s timeout=(%ss connect, %ss read) retries=%s",
            self.base_url,
            self.connect_timeout_seconds,
            self.read_timeout_seconds,
            self.max_retries,
        )

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

    def process_audio(self, audio_file) -> Dict:
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
                response = requests.post(
                    self.transcribe_endpoint,
                    files=files,
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

                question_type = reasoning.get("question_type", "unknown")
                needs_sql = reasoning.get("needs_sql", False)

                if not needs_sql or question_type != "analytical":
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
                        "raw_response": result,
                    }

                return {
                    "success": True,
                    "text": text,
                    "reasoning": reasoning,
                    "question_type": question_type,
                    "intent": llm_data.get("intent"),
                    "sql": llm_data.get("sql"),
                    "chart": llm_data.get("chart"),
                    "confidence": llm_data.get("confidence", 0.5),
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


_small_whisper_client = None


def get_small_whisper_client() -> SmallWhisperClient:
    global _small_whisper_client
    if _small_whisper_client is None:
        _small_whisper_client = SmallWhisperClient()
    return _small_whisper_client
