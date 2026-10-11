import os
import uuid
from pathlib import Path

# Use shared volume for uploaded files accessible by all services
BASE_DIR = "/app/uploaded_files"


def save_uploaded_file(uploaded_file):
    """
    Saves an uploaded file with a unique filename and returns absolute path.
    """

    if not os.path.exists(BASE_DIR):
        os.makedirs(BASE_DIR)

    unique_name = f"{uuid.uuid4()}_{uploaded_file.name}"
    file_path = os.path.join(BASE_DIR, unique_name)

    with open(file_path, "wb+") as destination:
        for chunk in uploaded_file.chunks():
            destination.write(chunk)

    return file_path


def save_sqlite_file(uploaded_file, workspace_id: int):
    """Store a validated SQLite file under a non-user-controlled opaque token."""
    max_size = int(os.getenv("ETL_SQLITE_MAX_BYTES", str(1024 * 1024 * 1024)))
    if int(getattr(uploaded_file, "size", 0)) <= 0 or uploaded_file.size > max_size:
        raise ValueError("SQLite file size is invalid or exceeds the configured limit.")
    extension = Path(str(uploaded_file.name or "")).suffix.lower()
    if extension not in {".db", ".sqlite", ".sqlite3"}:
        raise ValueError("SQLite files must use .db, .sqlite, or .sqlite3.")
    header = uploaded_file.read(16)
    uploaded_file.seek(0)
    if header != b"SQLite format 3\x00":
        raise ValueError("The uploaded file is not a valid SQLite 3 database.")
    os.makedirs(BASE_DIR, exist_ok=True)
    token = f"sqlite_{int(workspace_id)}_{uuid.uuid4().hex}.db"
    path = os.path.join(BASE_DIR, token)
    with open(path, "wb+") as destination:
        for chunk in uploaded_file.chunks():
            destination.write(chunk)
    return token
