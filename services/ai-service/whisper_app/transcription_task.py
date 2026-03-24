import whisper
import tempfile
import os

def full_audio_transcription(audio_bytes: bytes):
    """يعمل هذا داخل الـ worker"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    model = whisper.load_model("large-v3")
    result = model.transcribe(tmp_path)
    os.remove(tmp_path)

    return result["text"]