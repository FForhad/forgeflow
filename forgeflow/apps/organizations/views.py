from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.organizations.models import Membership, MembershipRole, Organization
from apps.organizations.permissions import (
    IsOrgAdminOrAbove,
    IsOrganizationMember,
    IsOrgOwner,
    IsOrgViewerOrAbove,
)
from apps.organizations.serializers import (
    MembershipCreateSerializer,
    MembershipSerializer,
    MembershipUpdateSerializer,
    OrganizationCreateSerializer,
    OrganizationSerializer,
)


class OrganizationListCreateView(generics.ListCreateAPIView):
    """
    List all organizations the authenticated user belongs to (Tenant Isolation),
    or create a new organization (user becomes OWNER).
    """
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return OrganizationCreateSerializer
        return OrganizationSerializer

    def get_queryset(self):
        # Strict Tenant Isolation: Only return organizations the user is a member of
        return Organization.objects.filter(memberships__user=self.request.user).distinct()


class OrganizationDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update, or delete an organization with role-based permissions:
    - View: VIEWER or above
    - Update: ADMIN or above
    - Delete: OWNER only
    """
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer

    def get_permissions(self):
        if self.request.method == 'DELETE':
            return [IsAuthenticated(), IsOrgOwner()]
        elif self.request.method in ['PUT', 'PATCH']:
            return [IsAuthenticated(), IsOrgAdminOrAbove()]
        return [IsAuthenticated(), IsOrgViewerOrAbove()]

    def get_object(self):
        org = get_object_or_404(Organization, pk=self.kwargs['pk'])
        self.check_object_permissions(self.request, org)
        return org


class MemberListCreateView(generics.ListCreateAPIView):
    """
    List members of an organization (VIEWER+) or invite/add a new member (ADMIN+).
    """
    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsOrgAdminOrAbove()]
        return [IsAuthenticated(), IsOrgViewerOrAbove()]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return MembershipCreateSerializer
        return MembershipSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['organization'] = get_object_or_404(Organization, pk=self.kwargs['organization_id'])
        return context

    def get_queryset(self):
        org = get_object_or_404(Organization, pk=self.kwargs['organization_id'])
        self.check_object_permissions(self.request, org)
        return Membership.objects.filter(organization=org).select_related('user')


class MemberDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Update member role (ADMIN+) or remove member from organization (ADMIN+).
    """
    def get_permissions(self):
        return [IsAuthenticated(), IsOrgAdminOrAbove()]

    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return MembershipUpdateSerializer
        return MembershipSerializer

    def get_object(self):
        org = get_object_or_404(Organization, pk=self.kwargs['organization_id'])
        self.check_object_permissions(self.request, org)
        membership = get_object_or_404(Membership, pk=self.kwargs['pk'], organization=org)
        return membership

    def perform_destroy(self, instance):
        if instance.role == MembershipRole.OWNER:
            owner_count = Membership.objects.filter(
                organization=instance.organization,
                role=MembershipRole.OWNER,
            ).count()
            if owner_count <= 1:
                raise ValidationError("Cannot remove the only OWNER of the organization.")
        instance.delete()
