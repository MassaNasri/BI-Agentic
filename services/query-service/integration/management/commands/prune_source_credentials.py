"""Scheduled removal of retired source credential ciphertext."""

from django.core.management.base import BaseCommand

from integration.credentials import prune_old_credentials


class Command(BaseCommand):
    help = "Expire superseded source ciphertext after grant and rollback retention."

    def handle(self, *args, **options):
        count = prune_old_credentials()
        self.stdout.write(f"Expired source credentials: {count}")
