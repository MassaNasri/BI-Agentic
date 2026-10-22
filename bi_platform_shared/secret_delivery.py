"""Small, fail-closed contract for externally injected application secrets.

Production deployments may provide NAME_FILE through a read-only secret mount.
The mount's lifecycle and backing secret manager belong to the deployment.
"""

import os
import stat
from pathlib import Path


class SecretDeliveryError(RuntimeError):
    pass


def read_secret(name, *, environment=None, production=None):
    environment = os.environ if environment is None else environment
    production = environment.get("APP_ENV") == "production" if production is None else production
    inline = str(environment.get(name, "") or "")
    file_name = str(environment.get(f"{name}_FILE", "") or "")
    if inline and file_name:
        raise SecretDeliveryError(f"{name} has two configured sources.")
    if not file_name:
        return inline
    path = Path(file_name)
    if not path.is_absolute() or path.is_symlink():
        raise SecretDeliveryError(f"{name} secret mount is invalid.")
    try:
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 16384:
            raise SecretDeliveryError(f"{name} secret mount is invalid.")
        if production and os.name == "posix" and info.st_mode & 0o077:
            raise SecretDeliveryError(f"{name} secret mount permissions are too broad.")
        value = path.read_text(encoding="utf-8").rstrip("\r\n")
    except (OSError, UnicodeError) as exc:
        raise SecretDeliveryError(f"{name} secret mount is unavailable.") from exc
    if not value:
        raise SecretDeliveryError(f"{name} secret mount is empty.")
    return value
