from rest_framework.permissions import BasePermission
from apps.organizations.models import Membership, MembershipRole

ROLE_WEIGHTS = {
    MembershipRole.OWNER: 4,
    MembershipRole.ADMIN: 3,
    MembershipRole.DEVELOPER: 2,
    MembershipRole.VIEWER: 1,
}


def get_user_role_in_org(user, organization_id):
    """
    Look up user's role in a given organization. Returns None if not a member.
    """
    if not user or not user.is_authenticated or not organization_id:
        return None
    membership = Membership.objects.filter(user=user, organization_id=organization_id).first()
    return membership.role if membership else None


class IsOrganizationMember(BasePermission):
    """
    Allows access only to authenticated users who are members of the organization.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        
        org_id = view.kwargs.get('organization_id') or view.kwargs.get('pk')
        if not org_id:
            return True
        return Membership.objects.filter(user=request.user, organization_id=org_id).exists()

    def has_object_permission(self, request, view, obj):
        org_id = getattr(obj, 'organization_id', None) or getattr(obj, 'id', None)
        return Membership.objects.filter(user=request.user, organization_id=org_id).exists()


class HasMinimumOrgRole(BasePermission):
    """
    Base permission class to enforce role hierarchy inside an organization:
    OWNER (4) > ADMIN (3) > DEVELOPER (2) > VIEWER (1)
    """
    min_role = MembershipRole.VIEWER

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        org_id = view.kwargs.get('organization_id') or view.kwargs.get('pk')
        if not org_id:
            return True

        role = get_user_role_in_org(request.user, org_id)
        if not role:
            return False

        return ROLE_WEIGHTS.get(role, 0) >= ROLE_WEIGHTS.get(self.min_role, 0)

    def has_object_permission(self, request, view, obj):
        org_id = getattr(obj, 'organization_id', None) or getattr(obj, 'id', None)
        role = get_user_role_in_org(request.user, org_id)
        if not role:
            return False
        return ROLE_WEIGHTS.get(role, 0) >= ROLE_WEIGHTS.get(self.min_role, 0)


class IsOrgViewerOrAbove(HasMinimumOrgRole):
    """Can view jobs, view org, and read-only actions."""
    min_role = MembershipRole.VIEWER


class IsOrgDeveloperOrAbove(HasMinimumOrgRole):
    """Can create jobs, cancel jobs, and trigger executions."""
    min_role = MembershipRole.DEVELOPER


class IsOrgAdminOrAbove(HasMinimumOrgRole):
    """Can manage members, invite members, and change team roles."""
    min_role = MembershipRole.ADMIN


class IsOrgOwner(HasMinimumOrgRole):
    """Can delete organization and perform root tenant administration."""
    min_role = MembershipRole.OWNER
