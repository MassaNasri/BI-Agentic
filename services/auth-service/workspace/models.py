from django.db import models
from django.utils import timezone
from django.conf import settings


class Workspace(models.Model):
    """Workspace model representing a manager's workspace."""
    
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='owned_workspaces'
    )
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'workspaces'
        verbose_name = 'Workspace'
        verbose_name_plural = 'Workspaces'
    
    def __str__(self):
        return f"{self.name} (Owner: {self.owner.email})"


class WorkspaceMember(models.Model):
    """Model representing workspace membership for Analysts and Executives."""
    
    STATUS_CHOICES = [
        ('pending_registration', 'Pending Registration'),
        ('pending_acceptance', 'Pending Acceptance'),
        ('active', 'Active'),
        ('suspended', 'Suspended'),
    ]
    
    ROLE_CHOICES = [
        ('analyst', 'Analyst'),
        ('executive', 'Executive'),
    ]
    
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='members'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='workspace_memberships',
        null=True,
        blank=True
    )
    invited_email = models.EmailField(null=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='analyst')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='active')
    invited_at = models.DateTimeField(default=timezone.now)
    joined_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'workspace_members'
        verbose_name = 'Workspace Member'
        verbose_name_plural = 'Workspace Members'
        indexes = [
            models.Index(fields=['workspace', 'user']),
            models.Index(fields=['workspace', 'invited_email']),
        ]
    
    def __str__(self):
        if self.user:
            return f"{self.user.email} in {self.workspace.name}"
        return f"{self.invited_email} (pending) in {self.workspace.name}"


class Invitation(models.Model):
    """Model representing workspace invitations sent to new members."""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('expired', 'Expired'),
    ]
    
    ROLE_CHOICES = [
        ('analyst', 'Analyst'),
        ('executive', 'Executive'),
    ]
    
    invited_email = models.EmailField()
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name='invitations'
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    token = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    
    class Meta:
        db_table = 'invitations'
        verbose_name = 'Invitation'
        verbose_name_plural = 'Invitations'
        # Only one pending invitation per email per workspace
        # Allows re-invitations after accepted/expired/removed
        constraints = [
            models.UniqueConstraint(
                fields=['invited_email', 'workspace'],
                condition=models.Q(status='pending'),
                name='unique_pending_invitation'
            )
        ]
    
    def __str__(self):
        return f"Invitation to {self.invited_email} for {self.workspace.name}"
    
    def is_expired(self):
        """Check if invitation has expired."""
        return timezone.now() > self.expires_at
    
    def save(self, *args, **kwargs):
        """Set expiration date to 48 hours from creation if not set."""
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(hours=48)
        super().save(*args, **kwargs)

