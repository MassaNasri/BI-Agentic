"""Remove only this application's expired, generated audio staging files."""

import os
from pathlib import Path
import re
import sys
import tempfile
import time


VOICE_NAME = re.compile(r'[0-9a-f]{32}\.(?:wav|mp3|m4a|ogg|webm)\Z')
AI_NAME = re.compile(r'biavora-audio-[A-Za-z0-9_-]+\.(?:wav|mp3|m4a|ogg|webm)\Z')
RETENTION_SECONDS = 24 * 60 * 60


def _remove_expired(directory, pattern, cutoff):
    removed = 0
    if not directory.is_dir() or directory.is_symlink():
        return removed
    for entry in os.scandir(directory):
        if (not entry.is_file(follow_symlinks=False) or not pattern.fullmatch(entry.name)):
            continue
        try:
            if entry.stat(follow_symlinks=False).st_mtime < cutoff:
                os.unlink(entry.path)
                removed += 1
        except FileNotFoundError:
            pass  # A request may have completed and deleted the file concurrently.
    return removed


def cleanup_voice_audio(root, *, now=None):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        return 0
    cutoff = (time.time() if now is None else now) - RETENTION_SECONDS
    removed = 0
    for workspace in os.scandir(root):
        if workspace.name.isdecimal() and workspace.is_dir(follow_symlinks=False):
            removed += _remove_expired(Path(workspace.path), VOICE_NAME, cutoff)
    return removed


def cleanup_ai_audio(root=None, *, now=None):
    cutoff = (time.time() if now is None else now) - RETENTION_SECONDS
    return _remove_expired(Path(root or tempfile.gettempdir()), AI_NAME, cutoff)


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in {'voice', 'ai'}:
        raise SystemExit('Expected voice or ai cleanup role.')
    if sys.argv[1] == 'voice':
        print(f'expired_voice_audio_removed={cleanup_voice_audio(Path.cwd() / "private_uploads")}')
    else:
        print(f'expired_ai_audio_removed={cleanup_ai_audio()}')
