from django.urls import path
from .views import (
    InternalActivateUserMembershipsView,
    InternalAttachUserToInvitationView,
    InternalCreateManagerWorkspaceView,
    InternalInvitationResolveView,
    InternalUserWorkspacesView,
    WorkspaceUpdateView,
    WorkspaceDetailByIdView,
    WorkspaceMembersView,
    InvitationView,
    RoleAssignmentView,
    MemberManageView,
    MemberSuspendView,
    MemberUnsuspendView,
    RemovePendingInvitationView,
    AcceptInvitationView
)

app_name = 'workspace'

urlpatterns = [
    path('', WorkspaceUpdateView.as_view(), name='workspace-update'),
    path('<int:workspace_id>/', WorkspaceDetailByIdView.as_view(), name='workspace-detail'),
    path('members/', WorkspaceMembersView.as_view(), name='workspace-members'),
    path('invite/', InvitationView.as_view(), name='workspace-invite'),
    path('accept-invite/', AcceptInvitationView.as_view(), name='accept-invite'),
    path('invitation/<str:email>/', RemovePendingInvitationView.as_view(), name='remove-invitation'),
    path('member/<int:id>/', MemberManageView.as_view(), name='member-manage'),
    path('member/<int:id>/role/', RoleAssignmentView.as_view(), name='assign-role'),
    path('member/<int:id>/suspend/', MemberSuspendView.as_view(), name='suspend-member'),
    path('member/<int:id>/unsuspend/', MemberUnsuspendView.as_view(), name='unsuspend-member'),
    path('internal/invitations/resolve/', InternalInvitationResolveView.as_view(), name='internal-invitation-resolve'),
    path('internal/invitations/attach-user/', InternalAttachUserToInvitationView.as_view(), name='internal-invitation-attach-user'),
    path('internal/workspaces/create-manager/', InternalCreateManagerWorkspaceView.as_view(), name='internal-create-manager-workspace'),
    path('internal/users/<int:user_id>/workspaces/', InternalUserWorkspacesView.as_view(), name='internal-user-workspaces'),
    path('internal/users/activate-memberships/', InternalActivateUserMembershipsView.as_view(), name='internal-activate-user-memberships'),
]

