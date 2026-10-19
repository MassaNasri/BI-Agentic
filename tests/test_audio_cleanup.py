import os
from pathlib import Path
from tempfile import TemporaryDirectory
import uuid

from bi_platform_shared.audio_cleanup import cleanup_ai_audio, cleanup_voice_audio


def test_expired_voice_audio_is_scoped_and_current_audio_is_kept():
    with TemporaryDirectory() as temp:
        root = Path(temp)
        workspace = root / '23'
        workspace.mkdir()
        old = workspace / f'{uuid.uuid4().hex}.wav'
        current = workspace / f'{uuid.uuid4().hex}.wav'
        unrelated = workspace / 'notes.txt'
        for file in (old, current, unrelated):
            file.write_bytes(b'data')
        os.utime(old, (1, 1))
        os.utime(unrelated, (1, 1))
        assert cleanup_voice_audio(root, now=90_000) == 1
        assert not old.exists()
        assert current.exists()
        assert unrelated.exists()


def test_expired_ai_audio_only_removes_generated_prefix():
    with TemporaryDirectory() as temp:
        root = Path(temp)
        old = root / 'biavora-audio-abc123.wav'
        unrelated = root / 'recording.wav'
        old.write_bytes(b'audio')
        unrelated.write_bytes(b'audio')
        os.utime(old, (1, 1))
        os.utime(unrelated, (1, 1))
        assert cleanup_ai_audio(root, now=90_000) == 1
        assert not old.exists()
        assert unrelated.exists()
