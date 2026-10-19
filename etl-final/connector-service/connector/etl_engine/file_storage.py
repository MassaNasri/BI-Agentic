import os
import re
import uuid
import time
from pathlib import Path

# Use shared volume for uploaded files accessible by all services
BASE_DIR = "/app/uploaded_files"
_DATASET_NAME = re.compile(r"[0-9a-f]{32}\.(?:csv|xlsx)\Z")
_SQLITE_NAME = re.compile(r"sqlite_[1-9][0-9]*_[0-9a-f]{32}\.db\Z")


def cleanup_expired_uploads(root=None, retention_seconds=86400):
    """Remove abandoned private source files older than the one-day staging TTL."""
    root = root or BASE_DIR
    if not os.path.isdir(root):
        return 0
    removed = 0
    cutoff = time.time() - retention_seconds
    for workspace in os.scandir(root):
        if (_SQLITE_NAME.fullmatch(workspace.name) and workspace.is_file(follow_symlinks=False)
                and workspace.stat(follow_symlinks=False).st_mtime < cutoff):
            os.unlink(workspace.path)
            removed += 1
            continue
        if (not workspace.name.isdecimal() or int(workspace.name) <= 0
                or not workspace.is_dir(follow_symlinks=False)):
            continue
        for entry in os.scandir(workspace.path):
            if (_DATASET_NAME.fullmatch(entry.name) and entry.is_file(follow_symlinks=False)
                    and entry.stat(follow_symlinks=False).st_mtime < cutoff):
                os.unlink(entry.path)
                removed += 1
    return removed


def save_uploaded_file(uploaded_file, workspace_id):
    """
    Saves an uploaded file with a unique filename and returns absolute path.
    """

    cleanup_expired_uploads()
    workspace_dir = os.path.join(BASE_DIR, str(int(workspace_id)))
    os.makedirs(workspace_dir, mode=0o700, exist_ok=True)
    extension = Path(uploaded_file.name).suffix.lower()
    file_path = os.path.join(workspace_dir, f"{uuid.uuid4().hex}{extension}")
    fd = os.open(file_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    total = 0
    try:
        with os.fdopen(fd, "wb") as destination:
            for chunk in uploaded_file.chunks():
                total += len(chunk)
                if total > 50 * 1024 * 1024:
                    raise ValueError('Upload exceeds size limit.')
                destination.write(chunk)
    except Exception:
        os.unlink(file_path)
        raise

    return file_path


def save_sqlite_file(uploaded_file, workspace_id: int):
    """Store a validated SQLite file under a non-user-controlled opaque token."""
    max_size = min(int(os.getenv("ETL_SQLITE_MAX_BYTES", str(100 * 1024 * 1024))), 100 * 1024 * 1024)
    if int(getattr(uploaded_file, "size", 0)) <= 0 or uploaded_file.size > max_size:
        raise ValueError("SQLite file size is invalid or exceeds the configured limit.")
    extension = Path(str(uploaded_file.name or "")).suffix.lower()
    if extension not in {".db", ".sqlite", ".sqlite3"}:
        raise ValueError("SQLite files must use .db, .sqlite, or .sqlite3.")
    header = uploaded_file.read(16)
    uploaded_file.seek(0)
    if header != b"SQLite format 3\x00":
        raise ValueError("The uploaded file is not a valid SQLite 3 database.")
    cleanup_expired_uploads()
    os.makedirs(BASE_DIR, mode=0o700, exist_ok=True)
    token = f"sqlite_{int(workspace_id)}_{uuid.uuid4().hex}.db"
    path = os.path.join(BASE_DIR, token)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    total = 0
    try:
        with os.fdopen(fd, "wb") as destination:
            for chunk in uploaded_file.chunks():
                total += len(chunk)
                if total > 100 * 1024 * 1024:
                    raise ValueError('SQLite upload exceeds size limit.')
                destination.write(chunk)
    except Exception:
        os.unlink(path)
        raise
    return token


def refresh_queued_sqlite_file(token, workspace_id: int):
    """Start the 24-hour retention clock at snapshot dispatch, not prepare."""
    workspace = int(workspace_id)
    if workspace <= 0 or not re.fullmatch(rf"sqlite_{workspace}_[0-9a-f]{{32}}\.db", str(token)):
        raise ValueError("Invalid workspace-scoped SQLite token.")
    path = os.path.join(BASE_DIR, token)
    if os.path.islink(path) or not os.path.isfile(path):
        raise ValueError("Prepared SQLite file was not found.")
    if time.time() - os.stat(path, follow_symlinks=False).st_mtime >= 86400:
        raise ValueError("Prepared SQLite file expired. Upload it again.")
    try:
        os.utime(path, None, follow_symlinks=False)
    except NotImplementedError:
        # Windows lacks this flag; the production Linux call remains no-follow.
        os.utime(path, None)
    return path
