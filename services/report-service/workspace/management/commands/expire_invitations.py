from django.core.management.base import BaseCommand
from workspace.models import Invitation


class Command(BaseCommand):
    help = 'Expire old invitations for a specific email to allow re-invitation'

    def add_arguments(self, parser):
        parser.add_argument('email', type=str, help='Email address to expire invitations for')

    def handle(self, *args, **options):
        email = options['email']
        
        self.stdout.write(f"\n🔍 Checking invitations for: {email}")
        self.stdout.write("="*60)
        
        invitations = Invitation.objects.filter(invited_email=email)
        self.stdout.write(f"\n📧 Total invitations found: {invitations.count()}\n")
        
        for inv in invitations:
            self.stdout.write(f"Invitation ID: {inv.id}")
            self.stdout.write(f"  Workspace: {inv.workspace.name} (ID: {inv.workspace.id})")
            self.stdout.write(f"  Status: {inv.status}")
            self.stdout.write(f"  Role: {inv.role}")
            self.stdout.write(f"  Created: {inv.created_at}")
            self.stdout.write()
        
        # Expire all non-expired invitations
        self.stdout.write("🔧 Expiring all non-expired invitations...")
        updated = Invitation.objects.filter(
            invited_email=email
        ).exclude(
            status='expired'
        ).update(status='expired')
        
        self.stdout.write(self.style.SUCCESS(f"\n✅ Expired {updated} invitation(s)"))
        self.stdout.write(self.style.SUCCESS(f"✅ You can now send a new invitation to {email}!\n"))

