from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.models import Job, JobStatus
from apps.jobs.serializers import JobCreateSerializer, JobSerializer
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.organizations.permissions import (
    ROLE_WEIGHTS,
    IsOrgDeveloperOrAbove,
    IsOrgViewerOrAbove,
)


class JobRootListCreateView(generics.ListCreateAPIView):
    """
    POST /api/v1/jobs/ - Create a job in user's organization (DEVELOPER+).
    GET  /api/v1/jobs/ - List jobs across organizations the user belongs to (Tenant Isolation).
    """
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return JobCreateSerializer
        return JobSerializer

    def get_queryset(self):
        # Tenant Isolation: only return jobs for orgs the user is a member of
        user_org_ids = Membership.objects.filter(
            user=self.request.user
        ).values_list('organization_id', flat=True)

        qs = Job.objects.filter(organization_id__in=user_org_ids).prefetch_related('attempts')

        # Query parameter filtering
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param.upper())

        queue_param = self.request.query_params.get('queue')
        if queue_param:
            qs = qs.filter(queue=queue_param)

        type_param = self.request.query_params.get('type')
        if type_param:
            qs = qs.filter(type=type_param)

        org_param = self.request.query_params.get('organization_id') or self.request.query_params.get('org')
        if org_param:
            qs = qs.filter(organization_id=org_param)

        return qs


class JobRootDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/jobs/{id}/ - Retrieve job details and attempts history.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = JobSerializer

    def get_object(self):
        job = get_object_or_404(Job.objects.prefetch_related('attempts'), pk=self.kwargs['pk'])

        # Verify user belongs to the job's organization
        is_member = Membership.objects.filter(
            user=self.request.user,
            organization=job.organization,
        ).exists()

        if not is_member:
            raise PermissionDenied("You do not have access to jobs in this organization.")

        return job


class JobRootCancelView(APIView):
    """
    POST /api/v1/jobs/{id}/cancel/ - Cancel an active job (DEVELOPER+).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        job = get_object_or_404(Job, pk=pk)

        membership = Membership.objects.filter(
            user=request.user,
            organization=job.organization,
        ).first()

        if not membership:
            raise PermissionDenied("You do not have access to jobs in this organization.")

        if ROLE_WEIGHTS.get(membership.role, 0) < ROLE_WEIGHTS[MembershipRole.DEVELOPER]:
            raise PermissionDenied("VIEWER role cannot cancel jobs. DEVELOPER or above is required.")

        if job.status in [JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.CANCELLED]:
            return Response(
                {"detail": f"Cannot cancel a job that is already {job.status}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        job.status = JobStatus.CANCELLED
        job.save(update_fields=['status'])
        return Response(JobSerializer(job).data, status=status.HTTP_200_OK)


# Scoped Views for nested routes (/api/v1/organizations/{org_id}/jobs/)

class JobListCreateView(generics.ListCreateAPIView):
    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsOrgDeveloperOrAbove()]
        return [IsAuthenticated(), IsOrgViewerOrAbove()]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return JobCreateSerializer
        return JobSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['organization'] = get_object_or_404(Organization, pk=self.kwargs['organization_id'])
        return context

    def get_queryset(self):
        org = get_object_or_404(Organization, pk=self.kwargs['organization_id'])
        self.check_object_permissions(self.request, org)
        return Job.objects.filter(organization=org).prefetch_related('attempts')


class JobDetailView(generics.RetrieveDestroyAPIView):
    def get_permissions(self):
        if self.request.method == 'DELETE':
            return [IsAuthenticated(), IsOrgDeveloperOrAbove()]
        return [IsAuthenticated(), IsOrgViewerOrAbove()]

    def get_serializer_class(self):
        return JobSerializer

    def get_object(self):
        org = get_object_or_404(Organization, pk=self.kwargs['organization_id'])
        self.check_object_permissions(self.request, org)
        job = get_object_or_404(Job, pk=self.kwargs['pk'], organization=org)
        return job


class JobCancelView(APIView):
    permission_classes = [IsAuthenticated, IsOrgDeveloperOrAbove]

    def post(self, request, organization_id, pk):
        org = get_object_or_404(Organization, pk=organization_id)
        self.check_object_permissions(request, org)
        job = get_object_or_404(Job, pk=pk, organization=org)

        if job.status in [JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.CANCELLED]:
            return Response(
                {"detail": f"Cannot cancel a job that is already {job.status}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        job.status = JobStatus.CANCELLED
        job.save(update_fields=['status'])
        return Response(JobSerializer(job).data, status=status.HTTP_200_OK)
