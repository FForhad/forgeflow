import uuid
from django.db import models
from django.utils import timezone


class JobStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    QUEUED = 'QUEUED', 'Queued'
    RUNNING = 'RUNNING', 'Running'
    SUCCESS = 'SUCCESS', 'Success'
    FAILED = 'FAILED', 'Failed'
    RETRYING = 'RETRYING', 'Retrying'
    CANCELLED = 'CANCELLED', 'Cancelled'


class JobPriority(models.IntegerChoices):
    LOW = 1, 'Low'
    MEDIUM = 2, 'Medium'
    HIGH = 3, 'High'
    CRITICAL = 4, 'Critical'


class Job(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'organizations.Organization',
        on_delete=models.CASCADE,
        related_name='jobs',
    )
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=100, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=JobStatus.choices,
        default=JobStatus.PENDING,
        db_index=True,
    )
    priority = models.IntegerField(
        choices=JobPriority.choices,
        default=JobPriority.MEDIUM,
        db_index=True,
    )
    queue = models.CharField(max_length=100, default='default', db_index=True)
    result = models.JSONField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    queued_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'jobs'
        verbose_name = 'Job'
        verbose_name_plural = 'Jobs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['queue', 'status', 'priority']),
        ]

    def __str__(self):
        return f"{self.name} ({self.type}) - {self.status}"


class AttemptStatus(models.TextChoices):
    RUNNING = 'RUNNING', 'Running'
    SUCCESS = 'SUCCESS', 'Success'
    FAILED = 'FAILED', 'Failed'
    TIMED_OUT = 'TIMED_OUT', 'Timed Out'


class JobAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        Job,
        on_delete=models.CASCADE,
        related_name='attempts',
    )
    attempt_number = models.PositiveIntegerField()
    worker_id = models.CharField(max_length=128, null=True, blank=True, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=AttemptStatus.choices,
        default=AttemptStatus.RUNNING,
        db_index=True,
    )
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    duration = models.DurationField(null=True, blank=True)

    class Meta:
        db_table = 'job_attempts'
        verbose_name = 'Job Attempt'
        verbose_name_plural = 'Job Attempts'
        ordering = ['job', 'attempt_number']
        constraints = [
            models.UniqueConstraint(
                fields=['job', 'attempt_number'],
                name='unique_job_attempt_number',
            )
        ]

    def __str__(self):
        return f"Job {self.job_id} - Attempt #{self.attempt_number} ({self.status})"
