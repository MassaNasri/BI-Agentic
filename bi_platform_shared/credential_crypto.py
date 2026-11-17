"""Authenticated encryption for versioned Integration source credentials.

Deployment supplies high-entropy CREDENTIAL_SECRET_KEY[_Vn] values.  Key versions
are retained until all ciphertext using them has been rewrapped or retired.
"""

import base64
import os
import re
from bi_platform_shared.secret_delivery import read_secret

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class CredentialCryptoError(RuntimeError):
    pass


_VERSION = re.compile(r"^v[1-9][0-9]{0,3}$")


def active_key_name():
    version = os.getenv("CREDENTIAL_KEY_VERSION", "v1")
    if not _VERSION.fullmatch(version):
        raise CredentialCryptoError("Invalid active credential key version.")
    versioned = f"CREDENTIAL_SECRET_KEY_{version.upper()}"
    if version == "v1" and not (os.getenv(versioned) or os.getenv(f"{versioned}_FILE")):
        return "CREDENTIAL_SECRET_KEY"
    return versioned


def _fernet(version):
    if not _VERSION.fullmatch(str(version)):
        raise CredentialCryptoError("Invalid credential key version.")
    secret = read_secret(f"CREDENTIAL_SECRET_KEY_{version.upper()}")
    if not secret and version == "v1":
        secret = read_secret("CREDENTIAL_SECRET_KEY")
    if not secret or (os.getenv("APP_ENV") == "production" and len(secret) < 32):
        raise CredentialCryptoError("Credential encryption key is unavailable.")
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None,
        info=b"biavora-integration-source-credential-v1",
    ).derive(secret.encode("utf-8"))
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_credential(value):
    if not isinstance(value, str) or not value:
        raise CredentialCryptoError("A source credential is required.")
    version = os.getenv("CREDENTIAL_KEY_VERSION", "v1")
    return version, _fernet(version).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_credential(version, ciphertext):
    try:
        if not isinstance(ciphertext, str) or not ciphertext:
            raise ValueError
        return _fernet(version).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise CredentialCryptoError("Stored source credential is invalid.") from exc
