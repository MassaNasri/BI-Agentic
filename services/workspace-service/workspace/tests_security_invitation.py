from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from workspace.views import AcceptInvitationView


class InvitationAcceptanceIdentityTests(SimpleTestCase):
    def test_matching_authenticated_identity_is_required(self):
        expected = {"id": 7, "email": "victim@example.test"}
        anonymous = SimpleNamespace(user=SimpleNamespace(is_authenticated=False))
        wrong = SimpleNamespace(
            user=SimpleNamespace(is_authenticated=True, id="8", pk="8", email="other@example.test")
        )
        right = SimpleNamespace(
            user=SimpleNamespace(is_authenticated=True, id="7", pk="7", email="Victim@example.test")
        )
        assert AcceptInvitationView._authenticated_actor_matches(anonymous, expected) is False
        assert AcceptInvitationView._authenticated_actor_matches(wrong, expected) is False
        assert AcceptInvitationView._authenticated_actor_matches(right, expected) is True

    def _request(self, user=None):
        return SimpleNamespace(
            query_params={"token": "invitation-token"},
            user=user or SimpleNamespace(is_authenticated=False),
        )

    @patch("workspace.views.Invitation.objects")
    def test_expired_and_replayed_invitations_are_rejected(self, objects):
        for invitation, message in [
            (SimpleNamespace(status="accepted"), "already been used"),
            (SimpleNamespace(status="expired", is_expired=Mock(return_value=True), save=Mock()), "expired"),
        ]:
            objects.select_for_update.return_value.select_related.return_value.filter.return_value.first.return_value = invitation
            response = AcceptInvitationView.get.__wrapped__(AcceptInvitationView(), self._request())
            self.assertEqual(response.status_code, 400)
            self.assertIn(message, response.data["message"])

    @patch("workspace.views._resolve_user_by_email")
    @patch("workspace.views.Invitation.objects")
    def test_wrong_authenticated_identity_cannot_accept(self, objects, resolve_user):
        invitation = SimpleNamespace(
            status="pending", is_expired=Mock(return_value=False),
            invited_email="victim@example.test", role="analyst",
            workspace=SimpleNamespace(id=42, name="Tenant B"),
        )
        objects.select_for_update.return_value.select_related.return_value.filter.return_value.first.return_value = invitation
        resolve_user.return_value = {"id": 7, "email": "victim@example.test"}
        request = self._request(SimpleNamespace(is_authenticated=True, id=8, pk=8, email="other@example.test"))
        response = AcceptInvitationView.get.__wrapped__(AcceptInvitationView(), request)
        self.assertEqual(response.status_code, 401)

    @patch("workspace.views.get_notification_client")
    @patch("workspace.views.WorkspaceMember.objects.update_or_create")
    @patch("workspace.views._resolve_user_by_email")
    @patch("workspace.views.Invitation.objects")
    def test_matching_identity_accepts_once(self, objects, resolve_user, update_member, notification_factory):
        invitation = SimpleNamespace(
            status="pending", is_expired=Mock(return_value=False), save=Mock(),
            invited_email="victim@example.test", role="analyst",
            workspace=SimpleNamespace(id=42, name="Tenant B", owner_email="owner@example.test", owner_name="Owner"),
        )
        objects.select_for_update.return_value.select_related.return_value.filter.return_value.first.return_value = invitation
        resolve_user.return_value = {
            "id": 7, "email": "victim@example.test", "name": "Victim",
            "role": "global-user", "is_active": True, "is_verified": True,
        }
        notification_factory.return_value.send_event.return_value = {"success": True}
        request = self._request(SimpleNamespace(is_authenticated=True, id=7, pk=7, email="victim@example.test"))
        response = AcceptInvitationView.get.__wrapped__(AcceptInvitationView(), request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(invitation.status, "accepted")
        update_member.assert_called_once()
