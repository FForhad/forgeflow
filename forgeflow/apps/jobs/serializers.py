from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from apps.jobs.models import Job, JobAttempt, JobStatus
from apps.organizations.models import Membership, MembershipRole, Organization
from apps.organizations.permissions import ROLE_WEIGHTS


class JobAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobAttempt
        fields = [
            'id',
            'attempt_number',
            'worker_id',
            'status',
            'started_at',
            'finished_at',
            'error',
            'duration',
        ]
        read_only_fields = ['id', 'started_at']


class JobSerializer(serializers.ModelSerializer):
    attempts = JobAttemptSerializer(many=True, read_only=True)
    organization_id = serializers.UUIDField(source='organization.id', read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)

    class Meta:
        model = Job
        fields = [
            'id',
            'organization_id',
            'organization_name',
            'name',
            'type',
            'payload',
            'status',
            'priority',
            'queue',
            'result',
            'error',
            'created_at',
            'queued_at',
            'started_at',
            'completed_at',
            'attempts',
        ]
        read_only_fields = [
            'id',
            'organization_id',
            'organization_name',
            'status',
            'result',
            'error',
            'created_at',
            'queued_at',
            'started_at',
            'completed_at',
            'attempts',
        ]


class JobCreateSerializer(serializers.ModelSerializer):
    organization_id = serializers.UUIDField(required=False, write_only=True)
    priority = serializers.IntegerField(default=2, required=False)
    queue = serializers.CharField(default='default', required=False)

    class Meta:
        model = Job
        fields = [
            'id',
            'organization_id',
            'name',
            'type',
            'payload',
            'priority',
            'queue',
            'status',
            'created_at',
        ]
        read_only_fields = ['id', 'status', 'created_at']

    def validate(self, attrs):
        request = self.context.get('request')
        user = request.user if request else None

        # 1. Resolve organization
        org = self.context.get('organization')
        org_id = attrs.pop('organization_id', None)

        if not org and org_id:
            try:
                org = Organization.objects.get(id=org_id)
            except Organization.DoesNotExist:
                raise serializers.ValidationError({'organization_id': 'Organization not found.'})

        if not org and request:
            # Check header
            header_org_id = request.headers.get('X-Organization-Id')
            if header_org_id:
                try:
                    org = Organization.objects.get(id=header_org_id)
                except (Organization.DoesNotExist, ValueError):
                    raise serializers.ValidationError({'organization_id': 'Organization from header not found.'})

        if not org and user and user.is_authenticated:
            # Check user's memberships
            memberships = list(Membership.objects.filter(user=user).select_related('organization'))
            if len(memberships) == 1:
                org = memberships[0].organization
            elif len(memberships) == 0:
                raise serializers.ValidationError(
                    {'organization': 'You must belong to at least one organization to create a job.'}
                )
            else:
                raise serializers.ValidationError(
                    {'organization': 'Please specify organization_id (you belong to multiple organizations).'}
                )

        if not org:
            raise serializers.ValidationError({'organization': 'Organization is required.'})

        # 2. Check RBAC (must be DEVELOPER or above in this org)
        if user and user.is_authenticated:
            membership = Membership.objects.filter(user=user, organization=org).first()
            if not membership:
                raise PermissionDenied("You are not a member of this organization.")
            if ROLE_WEIGHTS.get(membership.role, 0) < ROLE_WEIGHTS[MembershipRole.DEVELOPER]:
                raise PermissionDenied("VIEWER role cannot create jobs. DEVELOPER or above is required.")

        attrs['organization'] = org
        return attrs

    def create(self, validated_data):
        return Job.objects.create(**validated_data)

    def to_representation(self, instance):
        return JobSerializer(instance, context=self.context).data
