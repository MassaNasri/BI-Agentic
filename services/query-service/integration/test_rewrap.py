"""Operational key retirement keeps existing source records resolvable."""

import os
import secrets
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from bi_platform_shared.credential_crypto import decrypt_credential, encrypt_credential
from integration.models import DataSource, SourceCredential


class CredentialRewrapTests(TestCase):
    def test_rewrap_and_retirement_gate(self):
        keys = {
            "APP_ENV": "test",
            "CREDENTIAL_KEY_VERSION": "v1",
            "CREDENTIAL_SECRET_KEY_V1": secrets.token_urlsafe(40),
            "CREDENTIAL_SECRET_KEY_V2": secrets.token_urlsafe(40),
        }
        with patch.dict(os.environ, keys):
            source = DataSource.objects.create(
                workspace_id=7, created_by=11, name="synthetic", engine="postgresql",
            )
            old_version, ciphertext = encrypt_credential("synthetic-source-password")
            credential = SourceCredential.objects.create(
                source=source, version=1, key_version=old_version,
                ciphertext=ciphertext, state=SourceCredential.ACTIVE,
            )
            with self.assertRaises(CommandError):
                call_command("rewrap_source_credentials", from_version="v1", check_retire=True)
            os.environ["CREDENTIAL_KEY_VERSION"] = "v2"
            call_command("rewrap_source_credentials", from_version="v1", apply=True, stdout=StringIO())
            credential.refresh_from_db()
            self.assertEqual(credential.key_version, "v2")
            self.assertEqual(decrypt_credential("v2", credential.ciphertext), "synthetic-source-password")
            call_command("rewrap_source_credentials", from_version="v1", check_retire=True, stdout=StringIO())
            del os.environ["CREDENTIAL_SECRET_KEY_V1"]
            self.assertEqual(decrypt_credential("v2", credential.ciphertext), "synthetic-source-password")
