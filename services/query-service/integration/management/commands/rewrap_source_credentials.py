"""Re-encrypt retained source credentials under the configured active key version."""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from bi_platform_shared.credential_crypto import (
    CredentialCryptoError, decrypt_credential, encrypt_credential,
)
from bi_platform_shared.db_ownership import integration_atomic_alias
from integration.models import SourceCredential


class Command(BaseCommand):
    help = "Rewrap retained Integration ciphertext after staging the new key."

    def add_arguments(self, parser):
        parser.add_argument("--from-version", required=True)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--check-retire", action="store_true")

    def handle(self, *args, **options):
        old_version = options["from_version"]
        alias = integration_atomic_alias()
        queryset = SourceCredential.objects.using(alias).filter(
            key_version=old_version,
        ).exclude(ciphertext="")
        count = queryset.count()
        if options["check_retire"]:
            if count:
                raise CommandError(f"Old credential key still protects {count} records.")
            self.stdout.write("Old credential key retirement check: PASS")
            return
        if not options["apply"]:
            self.stdout.write(f"Credential records requiring rewrap: {count}")
            return
        changed = 0
        try:
            with transaction.atomic(using=alias):
                for credential in queryset.select_for_update().iterator(chunk_size=100):
                    plaintext = decrypt_credential(credential.key_version, credential.ciphertext)
                    new_version, ciphertext = encrypt_credential(plaintext)
                    if new_version == old_version:
                        raise CommandError("Active key version must differ from the retiring version.")
                    credential.key_version = new_version
                    credential.ciphertext = ciphertext
                    credential.save(using=alias, update_fields=["key_version", "ciphertext"])
                    changed += 1
        except CredentialCryptoError as exc:
            raise CommandError("Credential rewrap failed; old key must remain available.") from exc
        self.stdout.write(f"Credential records rewrapped: {changed}")
