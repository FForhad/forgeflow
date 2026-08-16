import datetime
from django.db.utils import IntegrityError
from django.test import TestCase
from django.utils import timezone
from apps.jobs.models import AttemptStatus, Job, JobAttempt, JobPriority, JobStatus
from apps.organizations.models import Organization


class JobAndJobAttemptModelTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(
            name='ForgeFlow Cloud',
            slug='forgeflow-cloud',
        )

    def test_create_job_initial_fields(self):
        job = Job.objects.create(
            organization=self.org,
            name='process-video-transcode',
            type='video.transcode',
            payload={'source_url': 's3://bucket/input.mp4', 'resolution': '1080p'},
            priority=JobPriority.HIGH,
            queue='heavy-compute',
        )
        self.assertEqual(job.status, JobStatus.PENDING)
        self.assertEqual(job.priority, JobPriority.HIGH)
        self.assertEqual(job.queue, 'heavy-compute')
        self.assertIsNotNone(job.created_at)
        self.assertIsNone(job.started_at)
        self.assertIsNone(job.completed_at)

    def test_job_attempts_history_observability(self):
        job = Job.objects.create(
            organization=self.org,
            name='sync-stripe-payments',
            type='billing.sync',
            payload={'customer_id': 'cus_12345'},
        )

        # Attempt 1: Failed
        attempt_1 = JobAttempt.objects.create(
            job=job,
            attempt_number=1,
            worker_id='worker-node-01',
            status=AttemptStatus.FAILED,
            started_at=timezone.now() - datetime.timedelta(minutes=5),
            finished_at=timezone.now() - datetime.timedelta(minutes=4),
            error='Connection timed out reaching payment gateway',
            duration=datetime.timedelta(seconds=60),
        )

        # Attempt 2: Failed
        attempt_2 = JobAttempt.objects.create(
            job=job,
            attempt_number=2,
            worker_id='worker-node-02',
            status=AttemptStatus.FAILED,
            started_at=timezone.now() - datetime.timedelta(minutes=3),
            finished_at=timezone.now() - datetime.timedelta(minutes=2),
            error='Gateway 502 Bad Gateway',
            duration=datetime.timedelta(seconds=60),
        )

        # Attempt 3: Success
        attempt_3 = JobAttempt.objects.create(
            job=job,
            attempt_number=3,
            worker_id='worker-node-03',
            status=AttemptStatus.SUCCESS,
            started_at=timezone.now() - datetime.timedelta(minutes=1),
            finished_at=timezone.now(),
            duration=datetime.timedelta(seconds=15),
        )

        # Verify full historical trail preserved
        attempts = list(job.attempts.all())
        self.assertEqual(len(attempts), 3)
        self.assertEqual(attempts[0].status, AttemptStatus.FAILED)
        self.assertEqual(attempts[1].status, AttemptStatus.FAILED)
        self.assertEqual(attempts[2].status, AttemptStatus.SUCCESS)

    def test_duplicate_attempt_number_on_same_job_raises_error(self):
        job = Job.objects.create(
            organization=self.org,
            name='generate-pdf-invoice',
            type='invoice.generate',
        )
        JobAttempt.objects.create(
            job=job,
            attempt_number=1,
            worker_id='worker-01',
            status=AttemptStatus.FAILED,
        )
        with self.assertRaises(IntegrityError):
            JobAttempt.objects.create(
                job=job,
                attempt_number=1,  # Duplicate attempt #1 on same job
                worker_id='worker-02',
                status=AttemptStatus.SUCCESS,
            )
