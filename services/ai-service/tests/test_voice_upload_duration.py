from types import SimpleNamespace
from unittest.mock import patch

import pytest

from bi_platform_shared.uploads import UploadRejected, probe_audio_duration


@patch('bi_platform_shared.uploads.subprocess.run')
def test_duration_limit_before_transcription(run):
    run.return_value = SimpleNamespace(stdout='600.1\n')
    with pytest.raises(UploadRejected):
        probe_audio_duration('/private/sample.wav')
    run.return_value = SimpleNamespace(stdout='30.0\n')
    assert probe_audio_duration('/private/sample.wav') == 30.0


@patch('bi_platform_shared.uploads.subprocess.run')
def test_undecodable_audio_fails_closed(run):
    run.return_value = SimpleNamespace(stdout='not-a-duration')
    with pytest.raises(UploadRejected):
        probe_audio_duration('/private/sample.wav')
