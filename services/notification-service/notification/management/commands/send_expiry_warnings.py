from django.core.management.base import BaseCommand

from notification.services import dispatch_subscription_expiry_warnings


class Command(BaseCommand):
    help = 'Send subscription expiry warning emails for configured lead times.'

    def handle(self, *args, **options):
        result = dispatch_subscription_expiry_warnings()
        self.stdout.write(
            self.style.SUCCESS(
                'Expiry warning dispatch completed '
                f"(sent={result.get('sent', 0)}, "
                f"failed={result.get('failed', 0)}, "
                f"skipped={result.get('skipped', 0)}, "
                f"matched={result.get('matched_subscriptions', 0)})"
            )
        )
