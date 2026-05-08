from rest_framework import serializers

from .models import Invitation, Workspace, WorkspaceMember


class WorkspaceSerializer(serializers.ModelSerializer):
<<<<<<< HEAD
    """Serializer for workspace basic information."""
    
    class Meta:
        model = Workspace
        fields = ['id', 'name', 'description', 'company_number', 'company_address', 'created_at']
        read_only_fields = ['id', 'created_at']
=======
    owner_id = serializers.IntegerField(source="owner", read_only=True)

    class Meta:
        model = Workspace
        fields = [
            "id",
            "name",
            "description",
            "company_number",
            "company_address",
            "created_at",
            "owner_id",
            "owner_name",
            "owner_email",
        ]
        read_only_fields = fields
>>>>>>> c791036 (final update)


class WorkspaceUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    company_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    company_address = serializers.CharField(required=False, allow_blank=True)


class InvitationRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    role = serializers.ChoiceField(choices=["analyst", "executive"], required=True)


class RoleAssignmentSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=["manager", "analyst", "executive"], required=True)


class MemberStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["active", "pending"], required=True)


class InternalInvitationResolveSerializer(serializers.Serializer):
    token = serializers.CharField(required=True)


class InternalAttachUserSerializer(serializers.Serializer):
    token = serializers.CharField(required=True)
    user_id = serializers.IntegerField(min_value=1)
    user_email = serializers.EmailField(required=True)
    user_name = serializers.CharField(required=False, allow_blank=True)
    user_role = serializers.ChoiceField(choices=["manager", "analyst", "executive"], required=True)
    is_verified = serializers.BooleanField(default=False)
    is_active = serializers.BooleanField(default=True)


class InternalCreateWorkspaceSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(min_value=1)
    user_email = serializers.EmailField(required=True)
    user_name = serializers.CharField(required=False, allow_blank=True)
    workspace_name = serializers.CharField(required=False, allow_blank=True)


class InternalUserActivationSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(min_value=1)
    user_email = serializers.EmailField(required=True)
    user_name = serializers.CharField(required=False, allow_blank=True)
    user_role = serializers.ChoiceField(choices=["manager", "analyst", "executive", "admin"], required=True)
    is_active = serializers.BooleanField(default=True)
    is_verified = serializers.BooleanField(default=True)


def serialize_member(member: WorkspaceMember) -> dict:
    return {
        "id": member.user_id,
        "name": member.user_name or "",
        "email": member.user_email or member.invited_email or "",
        "role": member.role,
        "status": member.status,
    }


def serialize_invitation(invitation: Invitation) -> dict:
    return {
        "id": invitation.id,
        "invited_email": invitation.invited_email,
        "workspace_id": invitation.workspace_id,
        "role": invitation.role,
        "status": invitation.status,
        "created_at": invitation.created_at,
        "expires_at": invitation.expires_at,
    }
