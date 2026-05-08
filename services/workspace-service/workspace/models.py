from django.db import models
from django.utils import timezone


class Workspace(models.Model):
    """Workspace domain owned by workspace-service."""

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    company_number = models.CharField(max_length=100, blank=True, default="")
    company_address = models.TextField(blank=True, default="")

    # Stored as an ID, not a FK to the auth domain.
    owner = models.PositiveBigIntegerField(db_column="owner_id", db_index=True)
    owner_email = models.EmailField(blank=True, default="")
    owner_name = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "workspaces"
        verbose_name = "Workspace"
        verbose_name_plural = "Workspaces"

    @property
    def owner_id(self) -> int:
        return int(self.owner)

    def __str__(self):
        owner_label = self.owner_email or f"owner:{self.owner}"
        return f"{self.name} ({owner_label})"


class WorkspaceMember(models.Model):
    """Workspace membership projection with auth-domain snapshot fields."""

    STATUS_CHOICES = [
        ("pending_registration", "Pending Registration"),
        ("pending_acceptance", "Pending Acceptance"),
        ("active", "Active"),
        ("suspended", "Suspended"),
    ]

    ROLE_CHOICES = [
        ("manager", "Manager"),
        ("analyst", "Analyst"),
        ("executive", "Executive"),
    ]

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="members",
    )

    # Stored as an ID, not a FK to the auth domain.
    user = models.PositiveBigIntegerField(
        db_column="user_id",
        null=True,
        blank=True,
        db_index=True,
    )
    user_email = models.EmailField(blank=True, default="")
    user_name = models.CharField(max_length=255, blank=True, default="")
    user_role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="analyst")
    is_user_active = models.BooleanField(default=True)
    is_user_verified = models.BooleanField(default=False)

    invited_email = models.EmailField(null=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="analyst")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="active")
    invited_at = models.DateTimeField(default=timezone.now)
    joined_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "workspace_members"
        verbose_name = "Workspace Member"
        verbose_name_plural = "Workspace Members"
        indexes = [
            models.Index(fields=["workspace", "user"]),
            models.Index(fields=["workspace", "invited_email"]),
        ]

    @property
    def user_id(self) -> int | None:
        return int(self.user) if self.user is not None else None

    def __str__(self):
        if self.user is not None:
            return f"user:{self.user} in {self.workspace.name}"
        return f"{self.invited_email} (pending) in {self.workspace.name}"


class Invitation(models.Model):
    """Workspace invitations."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("expired", "Expired"),
    ]

    ROLE_CHOICES = [
        ("analyst", "Analyst"),
        ("executive", "Executive"),
    ]

    invited_email = models.EmailField()
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    token = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "invitations"
        verbose_name = "Invitation"
        verbose_name_plural = "Invitations"
        constraints = [
            models.UniqueConstraint(
                fields=["invited_email", "workspace"],
                condition=models.Q(status="pending"),
                name="unique_pending_invitation",
            )
        ]

    def __str__(self):
        return f"Invitation to {self.invited_email} for {self.workspace.name}"

    def is_expired(self):
        return timezone.now() > self.expires_at

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(hours=48)
        super().save(*args, **kwargs)
