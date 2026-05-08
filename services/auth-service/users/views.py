from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from .serializers import (
    SignUpSerializer, LoginSerializer, LogoutSerializer,
    ProfileSerializer, UpdateProfileSerializer, DeactivateAccountSerializer,
    AdminUserSerializer, AdminUserUpdateSerializer,
    ChangePasswordSerializer, ForgotPasswordRequestSerializer,
    ForgotPasswordVerifySerializer, ForgotPasswordResetSerializer,
)
from .utils import generate_verification_token, send_verification_email, verify_email_token
from .models import User
from .notification_client import get_notification_client
from .internal_authentication import ServiceInternalTokenAuthentication
from .permissions import IsAdmin
from .services.workspace_client import WorkspaceServiceError, get_workspace_service_client
import logging

logger = logging.getLogger(__name__)


def _system_admin_profile_payload(user):
    return {
        'id': getattr(user, 'id', 0),
        'name': getattr(user, 'name', 'System Admin'),
        'first_name': 'System',
        'last_name': 'Admin',
        'email': getattr(user, 'email', ''),
        'role': 'admin',
        'is_verified': True,
        'is_active': True,
        'date_of_birth': None,
        'home_address': '',
        'created_at': getattr(user, 'created_at', None),
        'workspace': None,
        'is_system_admin': True,
    }


def _serialize_user_identity(user):
    return {
        'id': user.id,
        'email': user.email,
        'name': user.name,
        'role': user.role,
        'is_active': bool(user.is_active),
        'is_verified': bool(user.is_verified),
    }


class SignUpView(APIView):
    """
    API endpoint for user sign up.
    
    POST /auth/signup/
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        """
        Handle user sign up request.
        
        Input:
            - name: User's full name
            - email: User's email address (must be unique)
            - password: User's password
            - role: User's role (manager/analyst/executive)
            
        Behavior:
            - Validates input data
            - Creates new user with hashed password
            - Auto-creates workspace if role is manager
            - Generates email verification token
            - Sends verification email
            
        Output:
            - success: Boolean indicating success
            - message: Success message
            - data: User details (id, name, email, role)
            - workspace_created: Boolean (true if workspace was created)
        """
        serializer = SignUpSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(
                {
                    'success': False,
                    'message': 'Validation failed',
                    'errors': serializer.errors
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Create user and workspace (if manager)
            result = serializer.save()
            user = result['user']
            workspace = result['workspace']
            is_invited = result.get('is_invited', False)
            
            # Send verification email for ALL signups (both normal and invited users)
            # Generate verification token
            token = generate_verification_token(user.id)

            # Send activation email through notification-service.
            notification_client = get_notification_client()
            notification_result = notification_client.send_event(
                event_type='account_activation',
                event_key=f"account-activation:{user.id}:{token}",
                payload={
                    'email': user.email,
                    'user_name': user.name,
                    'token': token,
                },
            )
            email_sent = notification_result.get('success', False)

            # Transitional fallback to keep signup activation behavior stable
            # during notification-service rollout.
            if not email_sent:
                email_sent = send_verification_email(
                    user_email=user.email,
                    user_name=user.name,
                    token=token
                )
            
            if not email_sent:
                logger.warning(
                    f"User {user.id} created but verification email failed to send"
                )
            else:
                logger.info(f"Verification email sent to {user.email} (ID: {user.id})")
            
            # Set appropriate message based on signup type
            if is_invited:
                # Invited user - must verify email before accessing workspace
                message = 'Account created successfully. Please check your email to activate your account.'
            else:
                # Normal signup
                if user.is_verified:
                    message = 'Account updated successfully. An activation email has been sent to your email address.'
                else:
                    message = 'User registered successfully. Please check your email to verify your account.'
            
            # Prepare response
            response_data = {
                'success': True,
                'message': message,
                'data': {
                    'user_id': user.id,
                    'name': user.name,
                    'email': user.email,
                    'role': user.role,
                    'is_verified': user.is_verified,
                    'created_at': user.created_at.isoformat()
                },
                'workspace_created': workspace is not None,
                'is_invited': is_invited
            }
            
            if workspace:
                workspace_id = workspace.get('id') if isinstance(workspace, dict) else getattr(workspace, 'id', None)
                workspace_name = workspace.get('name') if isinstance(workspace, dict) else getattr(workspace, 'name', '')
                workspace_created_at = (
                    workspace.get('created_at')
                    if isinstance(workspace, dict)
                    else getattr(workspace, 'created_at', None)
                )
                response_data['data']['workspace'] = {
                    'id': workspace_id,
                    'name': workspace_name,
                    'created_at': (
                        workspace_created_at.isoformat()
                        if hasattr(workspace_created_at, 'isoformat')
                        else workspace_created_at
                    ),
                }
            
            return Response(response_data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error during sign up: {str(e)}")
            return Response(
                {
                    'success': False,
                    'message': 'An error occurred during registration',
                    'error': str(e)
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class EmailVerificationView(APIView):
    """
    API endpoint for email verification.
    
    GET /auth/verify-email/?token=<signed_token>
    """
    permission_classes = [AllowAny]
    
    def get(self, request):
        """
        Handle email verification request.
        
        Query Parameters:
            - token: Signed verification token
            
        Behavior:
            - Validates the token
            - Checks if user exists
            - Checks if account is already verified
            - Sets user.is_verified = True if valid
            
        Output:
            - success: Boolean indicating success
            - message: Status message
        """
        token = request.query_params.get('token')
        
        # Check if token is provided
        if not token:
            return Response(
                {
                    'success': False,
                    'message': 'Verification token is required.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verify token and get user_id
        success, user_id, error_type = verify_email_token(token)
        
        # Handle token validation errors
        if not success:
            if error_type == 'expired':
                return Response(
                    {
                        'success': False,
                        'message': 'Verification link expired.'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
            elif error_type == 'invalid':
                return Response(
                    {
                        'success': False,
                        'message': 'Invalid verification link.'
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Check if user exists
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            logger.warning(f"Verification attempted for non-existent user ID: {user_id}")
            return Response(
                {
                    'success': False,
                    'message': 'Invalid verification link.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if user is already verified
        if user.is_verified:
            logger.info(f"User {user.email} (ID: {user.id}) attempted verification but already verified")
            return Response(
                {
                    'success': True,
                    'message': 'Your account is already verified.'
                },
                status=status.HTTP_200_OK
            )
        
        # Verify the user
        try:
            user.is_verified = True
            user.save(update_fields=['is_verified'])

            activation_payload = get_workspace_service_client().activate_user_memberships(
                user_id=user.id,
                user_email=user.email,
                user_name=user.name,
                user_role=user.role,
                is_active=bool(user.is_active),
                is_verified=bool(user.is_verified),
            )
            notifications = activation_payload.get('notifications') if isinstance(activation_payload, dict) else []
            notification_client = get_notification_client()
            if isinstance(notifications, list):
                for event in notifications:
                    if not isinstance(event, dict):
                        continue
                    workspace_id = event.get('workspace_id')
                    notification_result = notification_client.send_event(
                        event_type='workspace_member_joined',
                        event_key=f"workspace-join:{workspace_id}:{user.id}",
                        payload={
                            'workspace_id': workspace_id,
                            'workspace_name': event.get('workspace_name'),
                            'owner_email': event.get('owner_email'),
                            'owner_name': event.get('owner_name'),
                            'recipient_emails': [event.get('owner_email')] if event.get('owner_email') else [],
                            'joined_user_id': user.id,
                            'joined_user_name': user.name,
                            'joined_user_email': user.email,
                            'joined_role': event.get('joined_role') or user.role,
                        },
                    )
                    if not notification_result.get('success'):
                        logger.warning(
                            "workspace_member_joined notification dispatch failed workspace=%s user=%s error=%s",
                            workspace_id,
                            user.id,
                            notification_result.get('error'),
                        )
            
            logger.info(f"User {user.email} (ID: {user.id}) successfully verified")
            
            return Response(
                {
                    'success': True,
                    'message': 'Your account has been verified. You can now log in.'
                },
                status=status.HTTP_200_OK
            )
            
        except WorkspaceServiceError as exc:
            logger.error("Workspace activation sync failed for user=%s error=%s", user.id, exc)
            return Response(
                {
                    'success': False,
                    'message': 'Account verified but workspace activation could not be synchronized.',
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception as e:
            logger.error(f"Error verifying user {user_id}: {str(e)}")
            return Response(
                {
                    'success': False,
                    'message': 'An error occurred during verification. Please try again.'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class LoginView(APIView):
    """
    API endpoint for user login.
    
    POST /auth/login/
    """
    permission_classes = [AllowAny]
    
    def post(self, request):
        """
        Handle user login request.
        
        Input:
            - email: User's email address (case-insensitive)
            - password: User's password
            
        Behavior:
            - Validates credentials
            - Checks if account is verified
            - Checks if account is suspended
            - Generates JWT access and refresh tokens
            - Returns tokens and user profile
            
        Output:
            - access: JWT access token
            - refresh: JWT refresh token
            - user: User information (id, name, email, role)
            - workspace: Workspace information based on role
                - Manager: {id, name} of owned workspace
                - Analyst/Executive: [{id, name}, ...] of joined workspaces
        
        Error Responses:
            - 400: Invalid credentials
            - 403: Account not verified or suspended
        """
        serializer = LoginSerializer(data=request.data)
        
        try:
            serializer.is_valid(raise_exception=True)
            
            # Get validated data with tokens and user info
            data = serializer.validated_data
            
            logger.info(f"User {data['user']['email']} logged in successfully")
            
            return Response(
                {
                    'success': True,
                    'message': 'Login successful',
                    'access': data['access'],
                    'refresh': data['refresh'],
                    'user': data['user'],
                    'workspace': data['workspace'],
                },
                status=status.HTTP_200_OK
            )
            
        except serializers.ValidationError as e:
            # Handle specific error cases
            error_detail = e.detail.get('detail', 'Invalid request')
            error_code = getattr(e.detail.get('detail', {}), 'code', None) if hasattr(e.detail.get('detail', {}), 'code') else None
            
            # Determine HTTP status code based on error type
            if 'not_verified' in str(e.detail) or 'Please verify your email' in str(error_detail):
                http_status = status.HTTP_403_FORBIDDEN
            elif 'account_suspended' in str(e.detail) or 'suspended' in str(error_detail):
                http_status = status.HTTP_403_FORBIDDEN
            else:
                http_status = status.HTTP_400_BAD_REQUEST
            
            logger.warning(f"Login failed: {error_detail}")
            
            return Response(
                {
                    'success': False,
                    'message': str(error_detail),
                },
                status=http_status
            )
        
        except Exception as e:
            logger.error(f"Error during login: {str(e)}")
            return Response(
                {
                    'success': False,
                    'message': 'An error occurred during login',
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class LogoutView(APIView):
    """
    API endpoint for user logout.
    
    POST /auth/logout/
    """
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        """
        Handle user logout request.
        
        Input:
            - refresh: JWT refresh token (required)
            
        Behavior:
            - Validates the refresh token
            - Blacklists the refresh token to prevent reuse
            - Access token expires naturally (short-lived)
            
        Output:
            - success: Boolean indicating success
            - message: "You have been logged out successfully."
        
        Error Responses:
            - 400: Missing or invalid refresh token
        """
        serializer = LogoutSerializer(data=request.data)
        
        try:
            serializer.is_valid(raise_exception=True)
            
            # Blacklist the refresh token
            serializer.save()
            
            logger.info(f"User {request.user.email} logged out successfully")
            
            return Response(
                {
                    'success': True,
                    'message': 'You have been logged out successfully.'
                },
                status=status.HTTP_200_OK
            )
            
        except serializers.ValidationError as e:
            # Handle validation errors
            error_detail = e.detail.get('detail', 'Invalid request')
            
            logger.warning(f"Logout failed for user {request.user.email}: {error_detail}")
            
            return Response(
                {
                    'success': False,
                    'message': str(error_detail) if isinstance(error_detail, str) else 'Invalid or expired refresh token.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        except Exception as e:
            logger.error(f"Error during logout for user {request.user.email}: {str(e)}")
            return Response(
                {
                    'success': False,
                    'message': 'An error occurred during logout'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ProfileView(APIView):
    """
    API endpoint for viewing and updating user profile.
    
    GET /user/profile/ - View own profile
    PUT /user/profile/ - Update name and/or email
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Get authenticated user's profile.
        
        Output:
            - id, name, email, role, is_verified, is_suspended, created_at
        """
        user = request.user
        if getattr(user, 'is_system_admin', False):
            return Response(
                {
                    'success': True,
                    'user': _system_admin_profile_payload(user),
                },
                status=status.HTTP_200_OK,
            )

        serializer = ProfileSerializer(user)
        
        return Response(
            {
                'success': True,
                'user': serializer.data
            },
            status=status.HTTP_200_OK
        )
    
    def put(self, request):
        """
        Update authenticated user's profile.
        
        Input:
            - name (optional): New name
            - email (optional): New email (triggers verification if changed)
            
        Business Rules:
            - Can only update name and email
            - Cannot update role, is_verified, or is_suspended
            - Email must be unique
            - Changing email sets is_verified = False and sends verification email
            
        Output:
            - success: Boolean
            - message: Status message
            - user: Updated user profile
        """
        user = request.user
        if getattr(user, 'is_system_admin', False):
            return Response(
                {
                    'success': False,
                    'message': 'System admin profile is managed through environment configuration.',
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = UpdateProfileSerializer(
            data=request.data,
            context={'request': request}
        )
        
        try:
            serializer.is_valid(raise_exception=True)
            
            # Update the user
            result = serializer.update(user, serializer.validated_data)
            updated_user = result['user']
            
            # Return updated profile
            profile_serializer = ProfileSerializer(updated_user)
            
            message = 'Profile updated successfully.'
            
            logger.info(f"User {updated_user.email} updated profile")
            
            return Response(
                {
                    'success': True,
                    'message': message,
                    'user': profile_serializer.data
                },
                status=status.HTTP_200_OK
            )
            
        except serializers.ValidationError as e:
            return Response(
                {
                    'success': False,
                    'message': 'Validation failed',
                    'errors': e.detail
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        except Exception as e:
            logger.error(f"Error updating profile for user {user.email}: {str(e)}")
            return Response(
                {
                    'success': False,
                    'message': 'An error occurred while updating profile'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ChangePasswordView(APIView):
    """
    API endpoint for changing password while authenticated.

    POST /user/change-password/
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if getattr(request.user, 'is_system_admin', False):
            return Response(
                {
                    'success': False,
                    'message': 'System admin password is managed through environment configuration.',
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ChangePasswordSerializer(
            data=request.data,
            context={'request': request},
        )

        try:
            serializer.is_valid(raise_exception=True)
            serializer.save()
            logger.info("Password changed successfully for user=%s", request.user.email)
            return Response(
                {
                    'success': True,
                    'message': 'Password updated successfully.',
                },
                status=status.HTTP_200_OK,
            )
        except serializers.ValidationError as e:
            return Response(
                {
                    'success': False,
                    'message': 'Validation failed',
                    'errors': e.detail,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error("Error changing password for user %s: %s", request.user.email, e)
            return Response(
                {
                    'success': False,
                    'message': 'An error occurred while changing password.',
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ForgotPasswordRequestView(APIView):
    """
    Request a password reset code.

    POST /auth/forgot-password/request/
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordRequestSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            result = serializer.save()
            expires_minutes = 15
            if isinstance(result, dict):
                expires_minutes = result.get('expires_minutes', 15)

            # Intentionally generic response to avoid leaking whether email exists.
            return Response(
                {
                    'success': True,
                    'message': 'If the account exists, a verification code was sent to the email address.',
                    'expires_in_minutes': expires_minutes,
                },
                status=status.HTTP_200_OK,
            )
        except serializers.ValidationError as e:
            return Response(
                {
                    'success': False,
                    'message': 'Validation failed.',
                    'errors': e.detail,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error("Forgot password request failed: %s", e, exc_info=True)
            return Response(
                {
                    'success': False,
                    'message': 'Unable to process forgot password request right now. Please try again shortly.',
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ForgotPasswordVerifyView(APIView):
    """
    Verify password reset code.

    POST /auth/forgot-password/verify/
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordVerifySerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            reset_code = serializer.save()
            return Response(
                {
                    'success': True,
                    'message': 'Code verified successfully.',
                    'reset_token': str(reset_code.verification_token),
                },
                status=status.HTTP_200_OK,
            )
        except serializers.ValidationError as e:
            return Response(
                {
                    'success': False,
                    'message': 'Verification failed.',
                    'errors': e.detail,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )


class ForgotPasswordResetView(APIView):
    """
    Reset password after successful code verification.

    POST /auth/forgot-password/reset/
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordResetSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(
                {
                    'success': True,
                    'message': 'Password reset successfully. Please log in with your new password.',
                },
                status=status.HTTP_200_OK,
            )
        except serializers.ValidationError as e:
            return Response(
                {
                    'success': False,
                    'message': 'Password reset failed.',
                    'errors': e.detail,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )


class DeactivateAccountView(APIView):
    """
    API endpoint for deactivating user account.
    
    DELETE /user/deactivate/
    """
    permission_classes = [IsAuthenticated]
    
    def delete(self, request):
        """
        Deactivate authenticated user's account.
        
        Input:
            - refresh: JWT refresh token (required for logout)
            
        Business Rules:
            - Sets is_active = False (does not delete user)
            - Blacklists refresh token (logs user out)
            - User cannot log in again after deactivation
            
        Output:
            - success: Boolean
            - message: "Your account has been deactivated."
        """
        if getattr(request.user, 'is_system_admin', False):
            return Response(
                {
                    'success': False,
                    'message': 'System admin account cannot be deactivated.',
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = DeactivateAccountSerializer(
            data=request.data,
            context={'request': request}
        )
        
        try:
            serializer.is_valid(raise_exception=True)
            
            # Deactivate account and blacklist token
            deactivated_user = serializer.save()
            
            logger.info(f"User {deactivated_user.email} (ID: {deactivated_user.id}) deactivated account")
            
            return Response(
                {
                    'success': True,
                    'message': 'Your account has been deactivated.'
                },
                status=status.HTTP_200_OK
            )
            
        except serializers.ValidationError as e:
            return Response(
                {
                    'success': False,
                    'message': 'Validation failed',
                    'errors': e.detail
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        except Exception as e:
            logger.error(f"Error deactivating account for user {request.user.email}: {str(e)}")
            return Response(
                {
                    'success': False,
                    'message': 'An error occurred while deactivating account'
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdminUsersView(APIView):
    """
    Admin API for global user management.

    GET /admin/users/
    """

    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request):
        users = User.objects.all().order_by('-created_at')
        serializer = AdminUserSerializer(users, many=True)
        return Response(
            {
                'success': True,
                'count': len(serializer.data),
                'users': serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class AdminUserDetailView(APIView):
    """
    Admin API for updating users globally.

    PATCH /admin/users/<user_id>/
    """

    permission_classes = [IsAuthenticated, IsAdmin]

    def patch(self, request, user_id):
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(
                {
                    'success': False,
                    'message': 'User not found.',
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = AdminUserUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated_user = serializer.update(user, serializer.validated_data)
        payload = AdminUserSerializer(updated_user).data
        return Response(
            {
                'success': True,
                'user': payload,
            },
            status=status.HTTP_200_OK,
        )


class InternalUserByEmailView(APIView):
    authentication_classes = [ServiceInternalTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        email = str(request.query_params.get('email') or '').strip().lower()
        if not email:
            return Response(
                {
                    'success': False,
                    'message': 'email query param is required.',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = User.objects.filter(email__iexact=email).first()
        if not user:
            return Response(
                {
                    'success': False,
                    'message': 'User not found.',
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {
                'success': True,
                'user': _serialize_user_identity(user),
            },
            status=status.HTTP_200_OK,
        )


class InternalUserDetailView(APIView):
    authentication_classes = [ServiceInternalTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response(
                {
                    'success': False,
                    'message': 'User not found.',
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            {
                'success': True,
                'user': _serialize_user_identity(user),
            },
            status=status.HTTP_200_OK,
        )

    def patch(self, request, user_id):
        user = User.objects.filter(id=user_id).first()
        if not user:
            return Response(
                {
                    'success': False,
                    'message': 'User not found.',
                },
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = AdminUserUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated_user = serializer.update(user, serializer.validated_data)
        return Response(
            {
                'success': True,
                'user': _serialize_user_identity(updated_user),
            },
            status=status.HTTP_200_OK,
        )

