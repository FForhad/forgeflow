from rest_framework import serializers
from apps.jobs.models import Job, JobAttempt, JobPriority, JobStatus


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

    class Meta:
        model = Job
        fields = [
            'id',
            'organization_id',
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
    class Meta:
        model = Job
        fields = ['id', 'name', 'type', 'payload', 'priority', 'queue', 'created_at']
        read_only_fields = ['id', 'created_at']

    def create(self, validated_data):
        organization = self.context['organization']
        return Job.objects.create(
            organization=organization,
            **validated_data,
        )
