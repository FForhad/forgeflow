from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.jobs.models import Job, JobStatus
from apps.jobs.serializers import JobCreateSerializer, JobSerializer
from apps.organizations.models import Organization
from apps.organizations.permissions import (
    IsOrgDeveloperOrAbove,
    IsOrgViewerOrAbove,
)


class JobListCreateView(generics.ListCreateAPIView):
    """
    List jobs (VIEWER+) or create a new job (DEVELOPER+) inside an organization.
    """
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
    """
    Retrieve job details (VIEWER+) or cancel/delete job (DEVELOPER+).
    """
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
    """
    Cancel an active job (DEVELOPER+).
    """
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
