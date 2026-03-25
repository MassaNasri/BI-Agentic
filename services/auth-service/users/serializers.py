from rest_framework import serializers
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
import secrets
import logging
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from .models import PasswordResetCode, User
from .notification_client import get_notification_client
from workspace.models import Workspace, WorkspaceMember

logger = logging.getLogger(__name__)


def split_full_name(full_name):
    cleaned = (full_name or '').strip()
    if not cleaned:
        return '', ''
    tokens = cleaned.split()
    if len(tokens) == 1:
        return tokens[0], ''
    return tokens[0], ' '.join(tokens[1:])


class SignUpSerializer(serializers.Serializer):
    """Serializer for user sign up."""
    
    name = serializers.CharField(max_length=255, required=True)
    email = serializers.EmailField(required=True)
    password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )
    role = serializers.ChoiceField(
        choices=['manager', 'analyst', 'executive'],
        required=False
    )
    invitation_token = serializers.CharField(required=False, allow_blank=True)
    
    def validate_email(self, value):
        """Validate that email is unique."""
        # Skip uniqueness check if this is an invitation signup
        # (we'll handle existing users in the create method)
        email = value.lower()
        admin_email = getattr(settings, 'ADMIN_EMAIL', '')
        if admin_email and email == admin_email:
            raise serializers.ValidationError('This email is reserved for the system administrator.')
        return email
    
    def validate_password(self, value):
        """Validate password strength using Django's password validators."""
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value
    
    def validate(self, attrs):
        """
        Validate signup data and handle invitation token.
        
        Two flows:
        1. Normal signup: requires email, role, name, password
        2. Invitation signup: requires name, password, invitation_token (email and role from invitation)
        """
        invitation_token = attrs.get('invitation_token')
        email = attrs.get('email')
        role = attrs.get('role')
        
        if invitation_token:
            # === INVITATION SIGNUP FLOW ===
            # Validate invitation token using workspace.utils
            from workspace.utils import validate_invitation_token
            
            try:
                workspace, invited_role, invited_email, invitation = validate_invitation_token(invitation_token)
            except serializers.ValidationError as e:
                raise serializers.ValidationError({"invitation_token": str(e.detail[0])})
            
            # Override email and role with values from invitation
            # User CANNOT modify these - they come from the invitation
            attrs['email'] = invited_email
            attrs['role'] = invited_role
            
            # Store invitation data for use in create()
            attrs['invitation_data'] = {
                'workspace': workspace,
                'invitation': invitation,
                'invited_email': invited_email,
                'role': invited_role,
            }
        else:
            # === NORMAL SIGNUP FLOW ===
            # Email and role are required
            if not email:
                raise serializers.ValidationError({"email": "Email is required."})
            
            if not role:
                raise serializers.ValidationError({"role": "Role is required when not signing up via invitation."})
            
            allowed_roles = ['manager', 'analyst', 'executive']
            if role not in allowed_roles:
                raise serializers.ValidationError({
                    "role": f"Role must be one of: {', '.join(allowed_roles)}"
                })

        admin_email = getattr(settings, 'ADMIN_EMAIL', '')
        if admin_email and attrs.get('email', '').lower() == admin_email:
            raise serializers.ValidationError(
                {"email": "This email is reserved for the system administrator."}
            )
        
        return attrs
    
    @transaction.atomic
    def create(self, validated_data):
        """
        Create user and auto-create workspace if role is manager.
        If signing up via invitation, update WorkspaceMember entry.
        
        Returns:
            dict with user, workspace, and is_invited flag
        """
        name = validated_data['name']
        email = validated_data['email']
        password = validated_data['password']
        role = validated_data['role']
        invitation_data = validated_data.get('invitation_data')
        first_name, last_name = split_full_name(name)
        
        workspace = None
        is_invited = False
        
        if invitation_data:
            # === INVITATION SIGNUP ===
            from django.utils import timezone
            
            workspace = invitation_data['workspace']
            invitation = invitation_data['invitation']
            
            # Check if user already exists with this email
            existing_user = User.objects.filter(email=email).first()
            
            if existing_user:
                # User already exists - update password and info
                existing_user.set_password(password)
                existing_user.name = name
                existing_user.first_name = first_name
                existing_user.last_name = last_name
                existing_user.role = role
                # Set is_verified=False if not already verified (needs email verification)
                if not existing_user.is_verified:
                    existing_user.is_verified = False
                existing_user.save()
                
                user = existing_user
                # Always send verification email for invited users
                is_invited = False  # Will trigger verification email in view
            else:
                # User doesn't exist - create new user with verified=False (needs email verification)
                user = User.objects.create_user(
                    email=email,
                    password=password,
                    name=name,
                    first_name=first_name,
                    last_name=last_name,
                    role=role,
                    is_verified=False  # Invited users must verify email
                )
                is_invited = False  # Send verification email
            
            # Determine WorkspaceMember status based on verification
            # If user is not verified, status should be 'pending_acceptance'
            member_status = 'active' if user.is_verified else 'pending_acceptance'
            
            # Get or create WorkspaceMember entry
            workspace_member, created = WorkspaceMember.objects.get_or_create(
                workspace=workspace,
                invited_email=email,
                defaults={
                    'user': user,
                    'role': role,
                    'status': member_status,
                    'joined_at': timezone.now() if user.is_verified else None
                }
            )
            
            # If already exists (from invitation creation), update it
            if not created:
                workspace_member.user = user
                workspace_member.status = member_status
                if user.is_verified:
                    workspace_member.joined_at = timezone.now()
                workspace_member.save()
            
            # Mark invitation as accepted
            invitation.status = 'accepted'
            invitation.save()
            
        else:
            # === NORMAL SIGNUP ===
            # Create user with verified=False (needs email verification)
            user = User.objects.create_user(
                email=email,
                password=password,
                name=name,
                first_name=first_name,
                last_name=last_name,
                role=role,
                is_verified=False  # Needs to verify email
            )
            
            # Auto-create workspace if role is manager
            if role == 'manager':
                workspace_name = f"{name}'s Workspace"
                workspace = Workspace.objects.create(
                    name=workspace_name,
                    owner=user
                )
        
        return {
            'user': user,
            'workspace': workspace,
            'is_invited': is_invited
        }


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model."""
    
    class Meta:
        model = User
        fields = [
            'id',
            'name',
            'first_name',
            'last_name',
            'email',
            'role',
            'is_verified',
            'date_of_birth',
            'home_address',
            'created_at',
        ]
        read_only_fields = ['id', 'is_verified', 'created_at']


class LoginSerializer(serializers.Serializer):
    """Serializer for user login with JWT token generation."""
    
    email = serializers.EmailField(required=True)
    password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )

    @staticmethod
    def _invalid_credentials_error():
        raise serializers.ValidationError(
            {'detail': 'Invalid login credentials.'},
            code='invalid_credentials'
        )

    @staticmethod
    def _build_system_admin_tokens(email):
        refresh = RefreshToken()
        refresh['user_id'] = int(getattr(settings, 'SYSTEM_ADMIN_USER_ID', 0))
        refresh['email'] = email
        refresh['name'] = getattr(settings, 'ADMIN_NAME', 'System Admin')
        refresh['role'] = 'admin'
        refresh['is_system_admin'] = True
        return str(refresh.access_token), str(refresh)
    
    def validate(self, attrs):
        """
        Validate login credentials and generate JWT tokens.
        
        Business Rules:
        - Email must exist (case-insensitive)
        - Password must be correct
        - User must be verified (is_verified == True)
        - User must not be suspended (is_active == True)
        
        Returns:
            dict with tokens and user information
        """
        email = attrs.get('email', '').lower()
        password = attrs.get('password')

        admin_email = getattr(settings, 'ADMIN_EMAIL', '')
        admin_password = getattr(settings, 'ADMIN_PASSWORD', '')
        if admin_email and email == admin_email:
            if not admin_password or password != admin_password:
                self._invalid_credentials_error()

            access_token, refresh_token = self._build_system_admin_tokens(email=admin_email)
            return {
                'access': access_token,
                'refresh': refresh_token,
                'user': {
                    'id': int(getattr(settings, 'SYSTEM_ADMIN_USER_ID', 0)),
                    'name': getattr(settings, 'ADMIN_NAME', 'System Admin'),
                    'email': admin_email,
                    'role': 'admin',
                    'is_system_admin': True,
                },
                'workspace': None,
            }
        
        # Check if user exists (case-insensitive email)
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            self._invalid_credentials_error()
        
        # Check password
        if not user.check_password(password):
            self._invalid_credentials_error()
        
        # Check if account is verified
        if not user.is_verified:
            raise serializers.ValidationError(
                {'detail': 'Please verify your email before logging in.'},
                code='not_verified'
            )
        
        # Check if account is suspended (using is_active field)
        if not user.is_active:
            raise serializers.ValidationError(
                {'detail': 'Your account is suspended.'},
                code='account_suspended'
            )
        
        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        refresh_token = str(refresh)
        
        # Prepare user info
        user_info = {
            'id': user.id,
            'name': user.name,
            'email': user.email,
            'role': user.role,
        }
        
        # Get workspace info based on role
        workspace_info = None
        
        if user.role == 'manager':
            # Manager: return owned workspace
            try:
                workspace = Workspace.objects.get(owner=user)
                workspace_info = {
                    'id': workspace.id,
                    'name': workspace.name,
                }
            except Workspace.DoesNotExist:
                workspace_info = None
        elif user.role in ['analyst', 'executive']:
            # Analyst or Executive: return list of joined workspaces
            memberships = WorkspaceMember.objects.filter(user=user).select_related('workspace')
            workspace_info = [
                {
                    'id': membership.workspace.id,
                    'name': membership.workspace.name,
                }
                for membership in memberships
            ]
        else:
            # Admin is system-level and not tied to a workspace.
            workspace_info = None
        
        return {
            'access': access_token,
            'refresh': refresh_token,
            'user': user_info,
            'workspace': workspace_info,
        }


class LogoutSerializer(serializers.Serializer):
    """Serializer for user logout with JWT token blacklisting."""
    
    refresh = serializers.CharField(required=True)
    
    def validate_refresh(self, value):
        """
        Validate that the refresh token is provided and valid.
        
        Args:
            value: The refresh token string
            
        Returns:
            The validated refresh token
            
        Raises:
            ValidationError: If token is missing or invalid
        """
        if not value:
            raise serializers.ValidationError("Refresh token is required.")
        return value
    
    def save(self):
        """
        Blacklist the refresh token to invalidate it.
        
        This prevents the refresh token from being used to generate
        new access tokens after logout.
        
        Returns:
            None
            
        Raises:
            ValidationError: If token is invalid or already blacklisted
        """
        refresh_token = self.validated_data['refresh']
        
        try:
            # Create RefreshToken instance and blacklist it
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError as e:
            raise serializers.ValidationError(
                {'detail': 'Invalid or expired refresh token.'},
                code='invalid_token'
            )
        except Exception as e:
            raise serializers.ValidationError(
                {'detail': 'Invalid or expired refresh token.'},
                code='invalid_token'
            )


class ProfileSerializer(serializers.ModelSerializer):
    """Serializer for viewing user profile."""
    workspace = serializers.SerializerMethodField()
    first_name = serializers.SerializerMethodField()
    last_name = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            'id',
            'name',
            'first_name',
            'last_name',
            'email',
            'role',
            'is_verified',
            'is_active',
            'date_of_birth',
            'home_address',
            'created_at',
            'workspace',
        ]
        read_only_fields = ['id', 'role', 'is_verified', 'is_active', 'created_at', 'workspace']

    def get_first_name(self, obj):
        if obj.first_name:
            return obj.first_name
        first_name, _ = split_full_name(obj.name)
        return first_name

    def get_last_name(self, obj):
        if obj.last_name:
            return obj.last_name
        _, last_name = split_full_name(obj.name)
        return last_name
    
    def get_workspace(self, obj):
        """Get workspace info based on user role."""
        if obj.role == 'manager':
            # Manager: return owned workspace
            workspace = obj.owned_workspaces.first()
            if workspace:
                return {
                    'id': workspace.id,
                    'name': workspace.name,
                }
            return None
        elif obj.role in ['analyst', 'executive']:
            # Analyst or Executive: return first active workspace
            membership = obj.workspace_memberships.filter(status='active').first()
            if membership:
                return {
                    'id': membership.workspace.id,
                    'name': membership.workspace.name,
                }
            return None
        return None


class UpdateProfileSerializer(serializers.Serializer):
    """Serializer for updating user profile fields (excluding email)."""

    first_name = serializers.CharField(max_length=150, required=False, allow_blank=False)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=False)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    home_address = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False)
    # Keep `name` accepted for backward compatibility with older clients.
    name = serializers.CharField(max_length=255, required=False, allow_blank=False)

    def validate_date_of_birth(self, value):
        if value and value > timezone.now().date():
            raise serializers.ValidationError("Date of birth cannot be in the future.")
        return value

    def update(self, instance, validated_data):
        """
        Update user profile details while keeping legacy `name` synchronized.
        """
        name_from_payload = validated_data.get('name')
        incoming_first_name = validated_data.get('first_name')
        incoming_last_name = validated_data.get('last_name')

        if name_from_payload and (incoming_first_name is None and incoming_last_name is None):
            parsed_first, parsed_last = split_full_name(name_from_payload)
            incoming_first_name = parsed_first
            incoming_last_name = parsed_last

        if incoming_first_name is not None:
            instance.first_name = incoming_first_name.strip()
        if incoming_last_name is not None:
            instance.last_name = incoming_last_name.strip()

        if 'date_of_birth' in validated_data:
            instance.date_of_birth = validated_data.get('date_of_birth')

        if 'home_address' in validated_data:
            instance.home_address = validated_data.get('home_address', '').strip()

        first_name_value = instance.first_name.strip()
        last_name_value = instance.last_name.strip()
        joined_name = " ".join(part for part in [first_name_value, last_name_value] if part).strip()
        if joined_name:
            instance.name = joined_name
        elif name_from_payload:
            instance.name = name_from_payload.strip()

        instance.save()
        return {'user': instance}


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})
    new_password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})
    confirm_new_password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})

    def validate_current_password(self, value):
        request = self.context.get('request')
        if request and request.user and not request.user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate(self, attrs):
        new_password = attrs.get('new_password')
        confirm_new_password = attrs.get('confirm_new_password')
        current_password = attrs.get('current_password')

        if new_password != confirm_new_password:
            raise serializers.ValidationError({'confirm_new_password': 'New password and confirmation do not match.'})

        if current_password == new_password:
            raise serializers.ValidationError({'new_password': 'New password must be different from current password.'})

        try:
            validate_password(new_password)
        except DjangoValidationError as e:
            raise serializers.ValidationError({'new_password': list(e.messages)})

        return attrs

    def save(self):
        request = self.context['request']
        user = request.user
        user.set_password(self.validated_data['new_password'])
        user.save(update_fields=['password'])
        return user


class ForgotPasswordRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)

    def validate_email(self, value):
        return value.strip().lower()

    def save(self):
        email = self.validated_data['email']
        expires_minutes = int(getattr(settings, 'PASSWORD_RESET_CODE_EXPIRY_MINUTES', 15))
        expires_at = timezone.now() + timedelta(minutes=expires_minutes)

        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if not user:
            return {
                'email_exists': False,
                'email': email,
                'expires_minutes': expires_minutes,
            }

        PasswordResetCode.objects.filter(
            user=user,
            is_used=False,
        ).update(is_used=True)

        verification_code = f"{secrets.randbelow(10**6):06d}"
        reset_code = PasswordResetCode.objects.create(
            user=user,
            email=user.email.lower(),
            code_hash=make_password(verification_code),
            expires_at=expires_at,
            is_verified=False,
            is_used=False,
            attempts=0,
        )

        notification_client = get_notification_client()
        try:
            notification_result = notification_client.send_event(
                event_type='password_reset_code',
                event_key=f"password-reset:{reset_code.id}:{reset_code.verification_token}",
                payload={
                    'email': user.email,
                    'user_name': user.name or 'there',
                    'code': verification_code,
                    'expires_minutes': expires_minutes,
                },
            )
            if not notification_result.get('success'):
                logger.error(
                    'Password reset email dispatch failed for user=%s reset_code_id=%s error=%s',
                    user.email,
                    reset_code.id,
                    notification_result.get('error'),
                )
        except Exception as exc:
            logger.error(
                'Password reset notification event failed unexpectedly for user=%s reset_code_id=%s error=%s',
                user.email,
                reset_code.id,
                exc,
                exc_info=True,
            )

        return {
            'email_exists': True,
            'email': user.email,
            'expires_minutes': expires_minutes,
        }


class ForgotPasswordVerifySerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    code = serializers.CharField(required=True, min_length=4, max_length=10)

    def validate_email(self, value):
        return value.strip().lower()

    def validate_code(self, value):
        return value.strip()

    def save(self):
        email = self.validated_data['email']
        code = self.validated_data['code']
        max_attempts = int(getattr(settings, 'PASSWORD_RESET_MAX_ATTEMPTS', 5))

        reset_code = PasswordResetCode.objects.filter(
            email=email,
            is_used=False,
        ).order_by('-created_at').first()

        if not reset_code:
            raise serializers.ValidationError({'code': 'Invalid or expired verification code.'})

        if reset_code.is_expired():
            reset_code.is_used = True
            reset_code.save(update_fields=['is_used'])
            raise serializers.ValidationError({'code': 'Invalid or expired verification code.'})

        if reset_code.attempts >= max_attempts:
            reset_code.is_used = True
            reset_code.save(update_fields=['is_used'])
            raise serializers.ValidationError({'code': 'Too many invalid attempts. Please request a new code.'})

        if not check_password(code, reset_code.code_hash):
            reset_code.attempts += 1
            if reset_code.attempts >= max_attempts:
                reset_code.is_used = True
            reset_code.save(update_fields=['attempts', 'is_used'])
            raise serializers.ValidationError({'code': 'Invalid or expired verification code.'})

        reset_code.is_verified = True
        reset_code.verified_at = timezone.now()
        reset_code.save(update_fields=['is_verified', 'verified_at'])
        return reset_code


class ForgotPasswordResetSerializer(serializers.Serializer):
    reset_token = serializers.UUIDField(required=True)
    new_password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})
    confirm_new_password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})

    def validate(self, attrs):
        new_password = attrs.get('new_password')
        confirm_new_password = attrs.get('confirm_new_password')
        if new_password != confirm_new_password:
            raise serializers.ValidationError({'confirm_new_password': 'New password and confirmation do not match.'})

        try:
            validate_password(new_password)
        except DjangoValidationError as e:
            raise serializers.ValidationError({'new_password': list(e.messages)})
        return attrs

    def save(self):
        reset_token = self.validated_data['reset_token']
        new_password = self.validated_data['new_password']
        reset_code = PasswordResetCode.objects.filter(
            verification_token=reset_token,
            is_used=False,
            is_verified=True,
        ).order_by('-created_at').first()

        if not reset_code or reset_code.is_expired():
            if reset_code and not reset_code.is_used:
                reset_code.is_used = True
                reset_code.save(update_fields=['is_used'])
            raise serializers.ValidationError({'reset_token': 'Invalid or expired reset token.'})

        user = reset_code.user
        user.set_password(new_password)
        user.save(update_fields=['password'])

        reset_code.is_used = True
        reset_code.save(update_fields=['is_used'])
        return user


class DeactivateAccountSerializer(serializers.Serializer):
    """Serializer for deactivating user account."""
    
    refresh = serializers.CharField(required=True)
    
    def validate_refresh(self, value):
        """Validate that refresh token is provided."""
        if not value:
            raise serializers.ValidationError("Refresh token is required.")
        return value
    
    def save(self):
        """
        Deactivate user account and blacklist refresh token.
        
        Returns:
            User instance
        """
        request = self.context.get('request')
        user = request.user
        
        # Deactivate account
        user.is_active = False
        user.save()
        
        # Try to blacklist refresh token (best effort)
        refresh_token = self.validated_data['refresh']
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except Exception:
            # Continue even if blacklisting fails
            pass
        
        return user


class AdminUserSerializer(serializers.ModelSerializer):
    """Serializer for admin user management endpoints."""

    class Meta:
        model = User
        fields = [
            'id',
            'name',
            'email',
            'role',
            'is_verified',
            'is_active',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class AdminUserUpdateSerializer(serializers.Serializer):
    """Serializer for patching users from admin APIs."""

    name = serializers.CharField(max_length=255, required=False)
    role = serializers.ChoiceField(
        choices=['manager', 'analyst', 'executive'],
        required=False,
    )
    is_active = serializers.BooleanField(required=False)
    is_verified = serializers.BooleanField(required=False)

    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        return instance
