from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
import uuid


class UserManager(BaseUserManager):
    """Custom user manager for email-based authentication."""
    
    def create_user(self, email, password=None, **extra_fields):
        """Create and return a regular user with an email and password."""
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        """Create and return a superuser with an email and password."""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_verified', True)
        extra_fields.setdefault('role', 'admin')
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Custom User model with email as the unique identifier."""
    
    ROLE_CHOICES = [
        ('admin', 'Admin'),
        ('manager', 'Manager'),
        ('analyst', 'Analyst'),
        ('executive', 'Executive'),
    ]
    
    name = models.CharField(max_length=255)
    first_name = models.CharField(max_length=150, blank=True, default='')
    last_name = models.CharField(max_length=150, blank=True, default='')
    email = models.EmailField(unique=True, db_index=True)
    password = models.CharField(max_length=255)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    is_verified = models.BooleanField(default=False)
    date_of_birth = models.DateField(null=True, blank=True)
    home_address = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(default=timezone.now)
    
    # Required fields for Django admin
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    
    objects = UserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name', 'role']
    
    class Meta:
        db_table = 'users'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
    
    def __str__(self):
        return f"{self.name} ({self.email})"


class PasswordResetCode(models.Model):
    """Password reset verification code lifecycle."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='password_reset_codes',
    )
    email = models.EmailField(db_index=True)
    code_hash = models.CharField(max_length=255)
    verification_token = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    is_verified = models.BooleanField(default=False)
    is_used = models.BooleanField(default=False)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'password_reset_codes'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email', 'is_used']),
            models.Index(fields=['user', 'is_used']),
            models.Index(fields=['expires_at']),
        ]

    def is_expired(self):
        return timezone.now() > self.expires_at

