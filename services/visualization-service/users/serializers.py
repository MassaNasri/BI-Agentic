from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from .models import User
from workspace.models import Workspace, WorkspaceMember


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
        return value.lower()
    
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
        fields = ['id', 'name', 'email', 'role', 'is_verified', 'created_at']
        read_only_fields = ['id', 'is_verified', 'created_at']


class LoginSerializer(serializers.Serializer):
    """Serializer for user login with JWT token generation."""
    
    email = serializers.EmailField(required=True)
    password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )
    
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
        
        # Check if user exists (case-insensitive email)
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                {'detail': 'Invalid login credentials.'},
                code='invalid_credentials'
            )
        
        # Check password
        if not user.check_password(password):
            raise serializers.ValidationError(
                {'detail': 'Invalid login credentials.'},
                code='invalid_credentials'
            )
        
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
        else:
            # Analyst or Executive: return list of joined workspaces
            memberships = WorkspaceMember.objects.filter(user=user).select_related('workspace')
            workspace_info = [
                {
                    'id': membership.workspace.id,
                    'name': membership.workspace.name,
                }
                for membership in memberships
            ]
        
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
    
    class Meta:
        model = User
        fields = ['id', 'name', 'email', 'role', 'is_verified', 'is_active', 'created_at', 'workspace']
        read_only_fields = ['id', 'role', 'is_verified', 'is_active', 'created_at', 'workspace']
    
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
        else:
            # Analyst or Executive: return first active workspace
            membership = obj.workspace_memberships.filter(status='active').first()
            if membership:
                return {
                    'id': membership.workspace.id,
                    'name': membership.workspace.name,
                }
            return None


class UpdateProfileSerializer(serializers.Serializer):
    """Serializer for updating user profile (name and email only)."""
    
    name = serializers.CharField(max_length=255, required=False)
    email = serializers.EmailField(required=False)
    
    def validate_email(self, value):
        """Validate that new email is unique."""
        if value:
            value = value.lower()
            request = self.context.get('request')
            if request and request.user:
                # Check if email is different from current user's email
                if value != request.user.email.lower():
                    # Check if email is already taken by another user
                    if User.objects.filter(email=value).exists():
                        raise serializers.ValidationError("This email is already in use.")
        return value
    
    def update(self, instance, validated_data):
        """
        Update user profile.
        
        If email changes, set is_verified = False.
        
        Returns:
            dict with 'user' and 'email_changed' keys
        """
        email_changed = False
        
        # Update name if provided
        if 'name' in validated_data:
            instance.name = validated_data['name']
        
        # Update email if provided and different
        if 'email' in validated_data:
            new_email = validated_data['email'].lower()
            if new_email != instance.email.lower():
                instance.email = new_email
                instance.is_verified = False
                email_changed = True
        
        instance.save()
        
        return {
            'user': instance,
            'email_changed': email_changed
        }


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
