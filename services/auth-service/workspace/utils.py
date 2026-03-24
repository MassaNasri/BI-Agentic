"""
Workspace utility functions
"""
from rest_framework import serializers
from django.utils import timezone
from .models import Invitation


def validate_invitation_token(token):
    """
    Validate invitation token by looking up in Invitation model.
    
    This function is used during signup-with-invitation flow.
    
    Args:
        token: Invitation token string (UUID-based)
        
    Returns:
        tuple: (workspace, role, invited_email)
        
    Raises:
        serializers.ValidationError: If token is invalid, expired, or already used
    """
    # Look up invitation by token
    try:
        invitation = Invitation.objects.select_related('workspace').get(token=token)
    except Invitation.DoesNotExist:
        raise serializers.ValidationError("Invalid or expired invitation link.")
    
    # Check if invitation is still pending
    if invitation.status == 'accepted':
        raise serializers.ValidationError("This invitation has already been accepted.")
    
    if invitation.status == 'expired':
        raise serializers.ValidationError("This invitation has expired.")
    
    # Check if invitation has expired (48 hours)
    if invitation.is_expired():
        invitation.status = 'expired'
        invitation.save()
        raise serializers.ValidationError("This invitation has expired.")
    
    # Return invitation details
    workspace = invitation.workspace
    role = invitation.role
    invited_email = invitation.invited_email
    
    return (workspace, role, invited_email, invitation)

