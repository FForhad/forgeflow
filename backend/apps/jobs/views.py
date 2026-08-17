from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
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


@extend_schema_view(
    get=extend_schema(
        tags=['Jobs'],
        summary='List jobs (with filters)',
        description='Lists all jobs belonging to organizations the authenticated user is a member of.',
        parameters=[
            OpenApiParameter(name='status', description='Filter by job status (PENDING, RUNNING, SUCCESS, FAILED, CANCELLED)', required=False, type=str),
            OpenApiParameter(name='queue', description='Filter by queue name', required=False, type=str),
            OpenApiParameter(name='type', description='Filter by job type', required=False, type=str),
            OpenApiParameter(name='organization_id', description='Filter by organization ID', required=False, type=str),
        ],
    ),
    post=extend_schema(
        tags=['Jobs'],
        summary='Submit and store a new job (initial status PENDING)',
        description='Submits a new job. User must have DEVELOPER or above role in the target organization.',
    ),
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
        user_org_ids = Membership.objects.filter(
            user=self.request.user
        ).values_list('organization_id', flat=True)

        qs = Job.objects.filter(organization_id__in=user_org_ids).prefetch_related('attempts')

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


@extend_schema_view(
    get=extend_schema(
        tags=['Jobs'],
        summary='Retrieve job details and attempt history',
        description='Returns job data, payload, state, timestamps, and list of execution attempts.',
    )
)
class JobRootDetailView(generics.RetrieveAPIView):
    """
    GET /api/v1/jobs/{id}/ - Retrieve job details and attempts history.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = JobSerializer

    def get_object(self):
        job = get_object_or_404(Job.objects.prefetch_related('attempts'), pk=self.kwargs['pk'])

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

    @extend_schema(
        tags=['Jobs'],
        summary='Cancel an active job',
        request=None,
        responses={
            200: JobSerializer,
            400: OpenApiResponse(description="Job cannot be cancelled (already SUCCESS, FAILED, or CANCELLED)"),
            403: OpenApiResponse(description="Permission denied (VIEWER cannot cancel jobs)"),
        },
    )
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


class JobRootEnqueueView(APIView):
    """
    POST /api/v1/jobs/{id}/enqueue/ - Enqueue a PENDING job into Redis (DEVELOPER+).
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Jobs'],
        summary='Enqueue a pending job into Redis queue',
        request=None,
        responses={
            200: JobSerializer,
            400: OpenApiResponse(description="Job is not in PENDING status"),
            403: OpenApiResponse(description="Permission denied"),
        },
    )
    def post(self, request, pk):
        job = get_object_or_404(Job, pk=pk)

        membership = Membership.objects.filter(
            user=request.user,
            organization=job.organization,
        ).first()

        if not membership:
            raise PermissionDenied("You do not have access to jobs in this organization.")

        if ROLE_WEIGHTS.get(membership.role, 0) < ROLE_WEIGHTS[MembershipRole.DEVELOPER]:
            raise PermissionDenied("VIEWER role cannot enqueue jobs. DEVELOPER or above is required.")

        if job.status != JobStatus.PENDING:
            return Response(
                {"detail": f"Cannot enqueue a job with status '{job.status}'. Only PENDING jobs can be enqueued."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.jobs.queue import enqueue_job
        enqueue_job(job)
        return Response(JobSerializer(job).data, status=status.HTTP_200_OK)


# Scoped Views for nested routes (/api/v1/organizations/{org_id}/jobs/)

@extend_schema_view(
    get=extend_schema(tags=['Organization Jobs'], summary='List jobs in organization (VIEWER+)'),
    post=extend_schema(tags=['Organization Jobs'], summary='Create job in organization (DEVELOPER+)'),
)
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


@extend_schema_view(
    get=extend_schema(tags=['Organization Jobs'], summary='Retrieve job in organization (VIEWER+)'),
    delete=extend_schema(tags=['Organization Jobs'], summary='Delete/Cancel job in organization (DEVELOPER+)'),
)
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

    @extend_schema(
        tags=['Organization Jobs'],
        summary='Cancel job in organization',
        request=None,
        responses={
            200: JobSerializer,
            400: OpenApiResponse(description="Cannot cancel completed or failed job"),
        },
    )
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


class JobEnqueueView(APIView):
    permission_classes = [IsAuthenticated, IsOrgDeveloperOrAbove]

    @extend_schema(
        tags=['Organization Jobs'],
        summary='Enqueue job in organization into Redis queue',
        request=None,
        responses={
            200: JobSerializer,
            400: OpenApiResponse(description="Cannot enqueue non-pending job"),
        },
    )
    def post(self, request, organization_id, pk):
        org = get_object_or_404(Organization, pk=organization_id)
        self.check_object_permissions(request, org)
        job = get_object_or_404(Job, pk=pk, organization=org)

        if job.status != JobStatus.PENDING:
            return Response(
                {"detail": f"Cannot enqueue a job with status '{job.status}'. Only PENDING jobs can be enqueued."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.jobs.queue import enqueue_job
        enqueue_job(job)
        return Response(JobSerializer(job).data, status=status.HTTP_200_OK)
