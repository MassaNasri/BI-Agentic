import logging
import os
import shutil
import tempfile
import threading
import time

import whisper
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from shared.pipeline import process_after_whisper

logger = logging.getLogger(__name__)

WHISPER_MODEL_NAME = os.getenv("WHISPER_MODEL_NAME", "tiny")
WHISPER_CACHE_DIR = os.getenv("WHISPER_CACHE_DIR", os.path.expanduser("~/.cache/whisper"))
WHISPER_TASK = os.getenv("WHISPER_TASK", "translate")

_model = None
_model_lock = threading.Lock()


def _load_model_with_retry():
    """
    Load Whisper lazily and retry once after clearing a corrupted cache.
    This avoids hard-crashing service startup when a partial model download exists.
    """
    last_error = None
    for attempt in range(2):
        try:
            started = time.perf_counter()
            logger.info(
                "Loading Whisper model '%s' from cache dir '%s' (attempt %s/2)",
                WHISPER_MODEL_NAME,
                WHISPER_CACHE_DIR,
                attempt + 1,
            )
            model = whisper.load_model(WHISPER_MODEL_NAME, download_root=WHISPER_CACHE_DIR)
            logger.info(
                "Whisper model '%s' loaded in %.2fs",
                WHISPER_MODEL_NAME,
                time.perf_counter() - started,
            )
            return model
        except RuntimeError as exc:
            last_error = exc
            message = str(exc).lower()
            if "checksum" in message and attempt == 0:
                logger.warning("Whisper checksum mismatch. Clearing cache directory '%s'.", WHISPER_CACHE_DIR)
                shutil.rmtree(WHISPER_CACHE_DIR, ignore_errors=True)
                continue
            raise
    raise last_error


def _get_model():
    global _model
    if _model is not None:
        return _model

    with _model_lock:
        if _model is None:
            _model = _load_model_with_retry()
    return _model


def _transcribe_audio_file(tmp_path: str) -> dict:
    model = _get_model()
    started = time.perf_counter()
    result = model.transcribe(tmp_path, task=WHISPER_TASK, verbose=False)
    logger.info(
        "Whisper transcription completed in %.2fs using model '%s'",
        time.perf_counter() - started,
        WHISPER_MODEL_NAME,
    )
    return result


@csrf_exempt
def transcribe_view(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    audio_file = request.FILES.get("audio")
    if not audio_file:
        return JsonResponse({"error": "No audio file provided"}, status=400)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        for chunk in audio_file.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        result = _transcribe_audio_file(tmp_path)
        text_result = result.get("text", "")
        reasoning_result, llm_result = process_after_whisper(text_result)
    except Exception as exc:
        logger.exception("Whisper transcription pipeline failed")
        return JsonResponse({"error": str(exc)}, status=500)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return JsonResponse(
        {
            "text": text_result,
            "reasoning": reasoning_result,
            "llm": llm_result,
        }
    )
