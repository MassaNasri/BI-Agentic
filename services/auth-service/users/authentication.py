from django.conf import settings
from django.utils import timezone
from rest_framework_simplejwt.authentication import JWTAuthentication


class SystemAdminUser:
    """
    Lightweight authenticated principal for env-configured system admin.
    """

    def __init__(self, email, name, user_id=0):
        self.id = user_id
        self.pk = user_id
        self.email = email
        self.name = name
        self.role = 'admin'
        self.is_active = True
        self.is_verified = True
        self.is_staff = True
        self.is_superuser = True
        self.is_system_admin = True
        self.created_at = timezone.now()

    @property
    def is_authenticated(self):
        return True

    def __str__(self):
        return f"{self.name} ({self.email})"


class ServiceJWTAuthentication(JWTAuthentication):
    """
    JWT auth with support for the single env-configured system admin token.
    """

    def get_user(self, validated_token):
        if bool(validated_token.get('is_system_admin')):
            configured_email = (getattr(settings, 'ADMIN_EMAIL', '') or '').strip().lower()
            token_email = str(validated_token.get('email', '')).strip().lower()
            token_role = str(validated_token.get('role', '')).strip().lower()

            if configured_email and token_email == configured_email and token_role == 'admin':
                admin_name = validated_token.get('name') or getattr(
                    settings,
                    'ADMIN_NAME',
                    'System Admin',
                )
                user_id = int(
                    validated_token.get('user_id') or getattr(settings, 'SYSTEM_ADMIN_USER_ID', 0)
                )
                return SystemAdminUser(email=configured_email, name=admin_name, user_id=user_id)

        return super().get_user(validated_token)
