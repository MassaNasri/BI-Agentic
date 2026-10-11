from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from rest_framework import serializers

from users.serializers import SignUpSerializer


class InvitationSignupSecurityTests(SimpleTestCase):
    def _serializer(self):
        return SignUpSerializer(
            data={
                "name": "Attacker Chosen Name",
                "email": "ignored@example.test",
                "password": "Attacker-chosen-password-123!",
                "confirm_password": "Attacker-chosen-password-123!",
                "invitation_token": "invite-token",
            }
        )

    @patch("users.serializers.User.objects.filter")
    @patch("users.serializers.get_workspace_service_client")
    def test_existing_account_invitation_is_not_account_recovery(self, client_factory, user_filter):
        client_factory.return_value.resolve_invitation.return_value = {
            "invited_email": "victim@example.test",
            "role": "analyst",
            "workspace_id": 42,
            "workspace_name": "Tenant B",
        }
        user_filter.return_value.exists.return_value = True

        serializer = self._serializer()

        assert serializer.is_valid() is False
        assert "Sign in as that account" in str(serializer.errors["invitation_token"][0])
        user_filter.return_value.first.assert_not_called()

    @patch("users.serializers.User.objects.create_user")
    @patch("users.serializers.User.objects.filter")
    @patch("users.serializers.get_workspace_service_client")
    @patch("django.db.transaction.Atomic.__exit__", return_value=None)
    @patch("django.db.transaction.Atomic.__enter__", return_value=None)
    def test_new_invited_identity_can_register(
        self, atomic_enter, atomic_exit, client_factory, user_filter, create_user
    ):
        client = client_factory.return_value
        client.resolve_invitation.return_value = {
            "invited_email": "new@example.test",
            "role": "executive",
            "workspace_id": 42,
            "workspace_name": "Tenant B",
        }
        client.attach_user_to_invitation.return_value = {"workspace_id": 42, "workspace_name": "Tenant B"}
        user_filter.return_value.exists.return_value = False
        create_user.return_value = Mock(id=7, email="new@example.test", name="New User", role="executive", is_verified=False, is_active=True)

        serializer = self._serializer()
        assert serializer.is_valid(), serializer.errors
        result = serializer.save()
        assert result["user"].email == "new@example.test"
        create_user.assert_called_once()
