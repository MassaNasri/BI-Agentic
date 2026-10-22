"""Restart-safe scheduled pruning for retired source credential ciphertext."""

import os
import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from integration.credentials import prune_old_credentials
from integration.limits import prune_source_operation_budgets


HEARTBEAT = Path("/tmp/credential-prune-heartbeat")


class Command(BaseCommand):
    help = "Run bounded periodic source credential pruning."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Prune once, then exit.")

    def handle(self, *args, **options):
        interval = int(os.getenv("CREDENTIAL_PRUNE_INTERVAL_SECONDS", "3600"))
        if not 60 <= interval <= 86400:
            raise ValueError("Credential prune interval must be between 60 and 86400 seconds.")
        while True:
            close_old_connections()
            count = prune_old_credentials()
            pruned_budgets = prune_source_operation_budgets()
            self.stdout.write(f"Expired source credentials: {count}")
            self.stdout.write(f"Expired source operation budgets: {pruned_budgets}")
            HEARTBEAT.write_text(str(int(time.time())), encoding="ascii")
            if options["once"]:
                return
            remaining = interval
            while remaining:
                step = min(30, remaining)
                time.sleep(step)
                remaining -= step
                HEARTBEAT.write_text(str(int(time.time())), encoding="ascii")
