import datetime
from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from apps.jobs.models import AttemptStatus, Job, JobAttempt, JobPriority, JobStatus
from apps.organizations.models import Membership, MembershipRole, Organization

User = get_user_model()


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


class JobRootAPITests(APITestCase):
    """
    Tests for direct REST API endpoints:
    POST /api/v1/jobs/
    GET  /api/v1/jobs/
    GET  /api/v1/jobs/{id}/
    POST /api/v1/jobs/{id}/cancel/
    """
    def setUp(self):
        self.user = User.objects.create_user(email='dev@forgeflow.dev', password='Password123!')
        self.org = Organization.objects.create(name='Acme Processing', slug='acme-proc')
        Membership.objects.create(user=self.user, organization=self.org, role=MembershipRole.DEVELOPER)

        self.jobs_url = reverse('job-list')

    def auth_user(self):
        token = str(AccessToken.for_user(self.user))
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_post_job_creates_pending_job_in_postgres(self):
        self.auth_user()
        payload = {
            "name": "generate-report",
            "type": "python_function",
            "payload": {
                "report_id": 123
            },
            "priority": 5,
            "queue": "default"
        }

        response = self.client.post(self.jobs_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data['name'], 'generate-report')
        self.assertEqual(data['type'], 'python_function')
        self.assertEqual(data['payload'], {'report_id': 123})
        self.assertEqual(data['priority'], 5)
        self.assertEqual(data['queue'], 'default')
        self.assertEqual(data['status'], 'PENDING')
        self.assertIsNotNone(data['id'])
        self.assertEqual(data['organization_id'], str(self.org.id))

        # Verify persisted in PostgreSQL
        job_in_db = Job.objects.get(id=data['id'])
        self.assertEqual(job_in_db.status, JobStatus.PENDING)
        self.assertEqual(job_in_db.priority, 5)
        self.assertEqual(job_in_db.organization, self.org)

    def test_get_jobs_list_and_filters(self):
        self.auth_user()
        job1 = Job.objects.create(
            organization=self.org,
            name='job-1',
            type='report.daily',
            status=JobStatus.PENDING,
            queue='default',
        )
        job2 = Job.objects.create(
            organization=self.org,
            name='job-2',
            type='video.render',
            status=JobStatus.RUNNING,
            queue='heavy',
        )

        # List all jobs
        response = self.client.get(self.jobs_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()), 2)

        # Filter by status=PENDING
        res_pending = self.client.get(f"{self.jobs_url}?status=PENDING")
        self.assertEqual(len(res_pending.json()), 1)
        self.assertEqual(res_pending.json()[0]['name'], 'job-1')

        # Filter by queue=heavy
        res_queue = self.client.get(f"{self.jobs_url}?queue=heavy")
        self.assertEqual(len(res_queue.json()), 1)
        self.assertEqual(res_queue.json()[0]['name'], 'job-2')

    def test_get_job_detail_by_id(self):
        self.auth_user()
        job = Job.objects.create(
            organization=self.org,
            name='invoice-pdf',
            type='invoice.generate',
            payload={'invoice_id': 456},
            status=JobStatus.PENDING,
        )

        detail_url = reverse('job-detail', kwargs={'pk': job.id})
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['id'], str(job.id))
        self.assertEqual(data['status'], 'PENDING')
        self.assertEqual(data['payload'], {'invoice_id': 456})
        self.assertEqual(data['attempts'], [])  # No worker picked it up yet

    def test_cancel_job_endpoint(self):
        self.auth_user()
        job = Job.objects.create(
            organization=self.org,
            name='sync-task',
            type='sync.full',
            status=JobStatus.PENDING,
        )

        cancel_url = reverse('job-cancel', kwargs={'pk': job.id})
        response = self.client.post(cancel_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['status'], 'CANCELLED')

        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.CANCELLED)

        # Attempting to cancel again returns 400
        res_again = self.client.post(cancel_url)
        self.assertEqual(res_again.status_code, status.HTTP_400_BAD_REQUEST)


class JobRBACAPITests(APITestCase):
    """
    Tests asserting the complete RBAC matrix:
    Action              Owner   Admin   Developer   Viewer  Outsider
    View jobs           ✓(200)  ✓(200)  ✓(200)      ✓(200)  ✗(403)
    Create jobs         ✓(201)  ✓(201)  ✓(201)      ✗(403)  ✗(403)
    Cancel jobs         ✓(200)  ✓(200)  ✓(200)      ✗(403)  ✗(403)
    """
    def setUp(self):
        self.owner = User.objects.create_user(email='owner@jobcorp.dev', password='Password123!')
        self.admin = User.objects.create_user(email='admin@jobcorp.dev', password='Password123!')
        self.dev = User.objects.create_user(email='dev@jobcorp.dev', password='Password123!')
        self.viewer = User.objects.create_user(email='viewer@jobcorp.dev', password='Password123!')
        self.outsider = User.objects.create_user(email='outsider@othercorp.dev', password='Password123!')

        self.org = Organization.objects.create(name='Job Corp', slug='job-corp')
        self.other_org = Organization.objects.create(name='Other Corp', slug='other-corp')

        Membership.objects.create(user=self.owner, organization=self.org, role=MembershipRole.OWNER)
        Membership.objects.create(user=self.admin, organization=self.org, role=MembershipRole.ADMIN)
        Membership.objects.create(user=self.dev, organization=self.org, role=MembershipRole.DEVELOPER)
        Membership.objects.create(user=self.viewer, organization=self.org, role=MembershipRole.VIEWER)

        # Create a sample job in Job Corp
        self.job = Job.objects.create(
            organization=self.org,
            name='email-newsletter-batch',
            type='email.batch',
            status=JobStatus.QUEUED,
        )

        self.list_create_url = reverse('org-jobs:org-job-list-create', kwargs={'organization_id': self.org.id})
        self.detail_url = reverse('org-jobs:org-job-detail', kwargs={'organization_id': self.org.id, 'pk': self.job.id})
        self.cancel_url = reverse('org-jobs:org-job-cancel', kwargs={'organization_id': self.org.id, 'pk': self.job.id})

    def auth_as(self, user):
        token = str(AccessToken.for_user(user))
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_view_jobs_rbac_all_org_members_allowed_outsider_denied(self):
        for user in [self.owner, self.admin, self.dev, self.viewer]:
            self.auth_as(user)
            response = self.client.get(self.list_create_url)
            self.assertEqual(response.status_code, status.HTTP_200_OK, f"User {user.email} should view jobs")

        # Outsider denied (Tenant Isolation)
        self.auth_as(self.outsider)
        response_outsider = self.client.get(self.list_create_url)
        self.assertEqual(response_outsider.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_jobs_rbac_matrix(self):
        payload = {
            'name': 'resize-image',
            'type': 'image.resize',
            'payload': {'width': 800, 'height': 600},
            'priority': 2,
        }

        # VIEWER is denied (403)
        self.auth_as(self.viewer)
        self.assertEqual(
            self.client.post(self.list_create_url, payload, format='json').status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # OUTSIDER is denied (403)
        self.auth_as(self.outsider)
        self.assertEqual(
            self.client.post(self.list_create_url, payload, format='json').status_code,
            status.HTTP_403_FORBIDDEN,
        )

        # DEVELOPER is allowed (201)
        self.auth_as(self.dev)
        self.assertEqual(
            self.client.post(self.list_create_url, payload, format='json').status_code,
            status.HTTP_201_CREATED,
        )

        # ADMIN is allowed (201)
        self.auth_as(self.admin)
        self.assertEqual(
            self.client.post(self.list_create_url, payload, format='json').status_code,
            status.HTTP_201_CREATED,
        )

        # OWNER is allowed (201)
        self.auth_as(self.owner)
        self.assertEqual(
            self.client.post(self.list_create_url, payload, format='json').status_code,
            status.HTTP_201_CREATED,
        )

    def test_cancel_jobs_rbac_matrix(self):
        # VIEWER is denied (403)
        self.auth_as(self.viewer)
        self.assertEqual(self.client.post(self.cancel_url).status_code, status.HTTP_403_FORBIDDEN)

        # DEVELOPER is allowed (200)
        self.auth_as(self.dev)
        response = self.client.post(self.cancel_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['status'], JobStatus.CANCELLED)


class RedisQueueTests(TestCase):
    def setUp(self):
        from apps.jobs.queue import RedisJobQueue
        self.queue = RedisJobQueue(key_prefix="test_jobs")
        self.queue.clear("default")
        self.queue.clear("high")

    def tearDown(self):
        self.queue.clear("default")
        self.queue.clear("high")

    def test_enqueue_and_dequeue_fifo(self):
        self.queue.enqueue("default", "job-1")
        self.queue.enqueue("default", "job-2")
        self.queue.enqueue("default", "job-3")

        self.assertEqual(self.queue.length("default"), 3)

        # First item out should be job-1 (FIFO)
        q_name, job_id = self.queue.dequeue("default", timeout=1)
        self.assertEqual(q_name, "default")
        self.assertEqual(job_id, "job-1")

        q_name, job_id = self.queue.dequeue("default", timeout=1)
        self.assertEqual(job_id, "job-2")

        q_name, job_id = self.queue.dequeue("default", timeout=1)
        self.assertEqual(job_id, "job-3")

        self.assertEqual(self.queue.length("default"), 0)

    def test_dequeue_timeout_when_empty(self):
        result = self.queue.dequeue("default", timeout=1)
        self.assertIsNone(result)

    def test_multi_queue_priority_order(self):
        # When checking ['high', 'default'], items in 'high' are popped first
        self.queue.enqueue("default", "default-job")
        self.queue.enqueue("high", "high-job")

        q_name, job_id = self.queue.dequeue(["high", "default"], timeout=1)
        self.assertEqual(q_name, "high")
        self.assertEqual(job_id, "high-job")

        q_name, job_id = self.queue.dequeue(["high", "default"], timeout=1)
        self.assertEqual(q_name, "default")
        self.assertEqual(job_id, "default-job")

    def test_peek_and_clear(self):
        self.queue.enqueue("default", "job-a")
        self.queue.enqueue("default", "job-b")
        peeked = self.queue.peek("default", count=5)
        self.assertIn("job-a", peeked)
        self.assertIn("job-b", peeked)

        self.queue.clear("default")
        self.assertEqual(self.queue.length("default"), 0)


class JobEnqueueAPITests(APITestCase):
    def setUp(self):
        from apps.jobs.queue import default_job_queue
        self.queue = default_job_queue
        self.queue.clear("default")

        self.user = User.objects.create_user(email='developer@jobflow.dev', password='Password123!')
        self.org = Organization.objects.create(name='JobFlow Corp', slug='jobflow-corp')
        Membership.objects.create(user=self.user, organization=self.org, role=MembershipRole.DEVELOPER)

        token = str(AccessToken.for_user(self.user))
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        self.job = Job.objects.create(
            organization=self.org,
            name='pending-task',
            type='echo',
            payload={'message': 'hello'},
            status=JobStatus.PENDING,
            queue='default',
        )
        self.enqueue_url = reverse('job-enqueue', kwargs={'pk': self.job.id})

    def tearDown(self):
        self.queue.clear("default")

    def test_enqueue_pending_job_updates_db_and_pushes_to_redis(self):
        response = self.client.post(self.enqueue_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['status'], 'QUEUED')
        self.assertIsNotNone(data['queued_at'])

        # Verify in DB
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, JobStatus.QUEUED)
        self.assertIsNotNone(self.job.queued_at)

        # Verify item in Redis queue
        self.assertEqual(self.queue.length("default"), 1)
        popped = self.queue.dequeue("default", timeout=1)
        self.assertEqual(popped[1], str(self.job.id))

    def test_enqueue_non_pending_job_returns_400(self):
        self.job.status = JobStatus.SUCCESS
        self.job.save()

        response = self.client.post(self.enqueue_url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Cannot enqueue", response.json()['detail'])

    def test_create_job_with_auto_enqueue(self):
        payload = {
            'organization_id': str(self.org.id),
            'name': 'auto-queued-job',
            'type': 'echo',
            'payload': {'key': 'val'},
            'queue': 'default',
            'auto_enqueue': True,
        }
        create_url = reverse('job-list')
        response = self.client.post(create_url, payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.json()['status'], 'QUEUED')

        # Verify job was enqueued in Redis
        popped = self.queue.dequeue("default", timeout=1)
        self.assertEqual(popped[1], response.json()['id'])


class CustomWorkerExecutionTests(TestCase):
    def setUp(self):
        from apps.jobs.queue import RedisJobQueue
        self.queue = RedisJobQueue(key_prefix="test_worker_jobs")
        self.queue.clear("default")
        self.queue.clear("high")

        self.org = Organization.objects.create(name='Worker Org', slug='worker-org')
        from apps.jobs.worker import CustomWorker
        self.worker = CustomWorker(
            queues=["high", "default"],
            timeout=1,
            worker_id="test-worker-001",
            queue_instance=self.queue,
        )

    def tearDown(self):
        self.queue.clear("default")
        self.queue.clear("high")

    def test_worker_processes_echo_job_successfully(self):
        job = Job.objects.create(
            organization=self.org,
            name='test-echo',
            type='echo',
            payload={'greeting': 'ForgeFlow Worker'},
            status=JobStatus.QUEUED,
            queue='default',
        )
        self.queue.enqueue("default", str(job.id))

        processed = self.worker.run(burst=True)
        self.assertEqual(processed, 1)

        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.SUCCESS)
        self.assertEqual(job.result, {"status": "echoed", "data": {"greeting": "ForgeFlow Worker"}})
        self.assertIsNotNone(job.started_at)
        self.assertIsNotNone(job.completed_at)
        self.assertIsNone(job.error)

        # Check attempt audit log
        attempts = list(job.attempts.all())
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].status, AttemptStatus.SUCCESS)
        self.assertEqual(attempts[0].worker_id, "test-worker-001")
        self.assertIsNotNone(attempts[0].duration)

    def test_worker_processes_math_compute_job_successfully(self):
        job = Job.objects.create(
            organization=self.org,
            name='test-math',
            type='math_compute',
            payload={'op': 'multiply', 'a': 6, 'b': 7},
            status=JobStatus.QUEUED,
            queue='high',
        )
        self.queue.enqueue("high", str(job.id))

        processed = self.worker.run(burst=True)
        self.assertEqual(processed, 1)

        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.SUCCESS)
        self.assertEqual(job.result['result'], 42.0)

    def test_worker_handles_failing_job_and_captures_traceback(self):
        job = Job.objects.create(
            organization=self.org,
            name='test-fail',
            type='failing_task',
            payload={'error_message': 'Simulated DB deadlock in worker'},
            status=JobStatus.QUEUED,
            queue='default',
            max_retries=0,
        )
        self.queue.enqueue("default", str(job.id))

        processed = self.worker.run(burst=True)
        self.assertEqual(processed, 1)

        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertIn("Simulated DB deadlock", job.error)
        self.assertIsNotNone(job.completed_at)

        attempts = list(job.attempts.all())
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].status, AttemptStatus.FAILED)
        self.assertIn("RuntimeError", attempts[0].error)

    def test_worker_handles_unknown_task_type(self):
        job = Job.objects.create(
            organization=self.org,
            name='test-unknown',
            type='non_existent_task_type',
            payload={},
            status=JobStatus.QUEUED,
            queue='default',
        )
        self.queue.enqueue("default", str(job.id))

        processed = self.worker.run(burst=True)
        self.assertEqual(processed, 1)

        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertIn("No handler registered", job.error)

    def test_worker_skips_cancelled_job(self):
        job = Job.objects.create(
            organization=self.org,
            name='test-cancelled',
            type='echo',
            payload={},
            status=JobStatus.CANCELLED,
            queue='default',
        )
        self.queue.enqueue("default", str(job.id))

        processed = self.worker.run(burst=True)
        self.assertEqual(processed, 0)

        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.CANCELLED)
        self.assertEqual(job.attempts.count(), 0)

    def test_worker_handles_nonexistent_job_gracefully(self):
        # Enqueue a random UUID not in database
        import uuid
        self.queue.enqueue("default", str(uuid.uuid4()))

        processed = self.worker.run(burst=True)
        self.assertEqual(processed, 0)


class ExponentialBackoffUnitTests(TestCase):
    def test_exponential_formula_delays(self):
        from apps.jobs.backoff import compute_backoff_delay

        # Base = 2s
        self.assertEqual(compute_backoff_delay(attempt=1, base=2), 2.0)   # 2 * 2^0
        self.assertEqual(compute_backoff_delay(attempt=2, base=2), 4.0)   # 2 * 2^1
        self.assertEqual(compute_backoff_delay(attempt=3, base=2), 8.0)   # 2 * 2^2
        self.assertEqual(compute_backoff_delay(attempt=4, base=2), 16.0)  # 2 * 2^3
        self.assertEqual(compute_backoff_delay(attempt=5, base=2), 32.0)  # 2 * 2^4

    def test_max_backoff_capping(self):
        from apps.jobs.backoff import compute_backoff_delay

        # Even with attempt 10, capped at max_backoff (60s)
        delay = compute_backoff_delay(attempt=10, base=2, max_backoff=60)
        self.assertEqual(delay, 60.0)

    def test_jitter_bounds(self):
        from apps.jobs.backoff import compute_backoff_delay

        for attempt in range(1, 6):
            delay = compute_backoff_delay(attempt=attempt, base=2, use_jitter=True)
            max_bound = 2 * (2 ** (attempt - 1))
            self.assertGreaterEqual(delay, 0.0)
            self.assertLessEqual(delay, max_bound)


class RetryableExceptionUnitTests(TestCase):
    def test_transient_exceptions_classified_as_retryable(self):
        from apps.jobs.exceptions import (
            DatabaseTemporaryLockError,
            NetworkTimeoutError,
            RateLimitExceededError,
            RetryableJobError,
            ServiceUnavailableError,
            is_retryable_exception,
        )

        self.assertTrue(is_retryable_exception(NetworkTimeoutError("timeout")))
        self.assertTrue(is_retryable_exception(ServiceUnavailableError("503")))
        self.assertTrue(is_retryable_exception(RateLimitExceededError("429")))
        self.assertTrue(is_retryable_exception(DatabaseTemporaryLockError("locked")))
        self.assertTrue(is_retryable_exception(RetryableJobError("generic transient")))
        self.assertTrue(is_retryable_exception(TimeoutError("socket timeout")))
        self.assertTrue(is_retryable_exception(ConnectionRefusedError("refused")))

    def test_permanent_exceptions_classified_as_non_retryable(self):
        from apps.jobs.exceptions import (
            InvalidPayloadError,
            NonRetryableJobError,
            PermissionDeniedTaskError,
            ResourceNotFoundError,
            is_retryable_exception,
        )

        self.assertFalse(is_retryable_exception(InvalidPayloadError("bad json")))
        self.assertFalse(is_retryable_exception(ResourceNotFoundError("missing")))
        self.assertFalse(is_retryable_exception(PermissionDeniedTaskError("403")))
        self.assertFalse(is_retryable_exception(NonRetryableJobError("fatal")))
        self.assertFalse(is_retryable_exception(ValueError("invalid val")))
        self.assertFalse(is_retryable_exception(KeyError("missing key")))
        self.assertFalse(is_retryable_exception(ZeroDivisionError("div 0")))
        self.assertFalse(is_retryable_exception(TypeError("type mismatch")))


class DelayedQueueRedisTests(TestCase):
    def setUp(self):
        from apps.jobs.queue import RedisJobQueue
        self.queue = RedisJobQueue(key_prefix="test_delayed_queue")
        self.queue.clear("default")
        self.queue.clear_delayed()

    def tearDown(self):
        self.queue.clear("default")
        self.queue.clear_delayed()

    def test_schedule_delayed_and_promote(self):
        # 1. Schedule a delayed job with 0s delay (immediately due)
        self.queue.schedule_delayed("default", "delayed-job-123", delay_seconds=0)
        self.assertEqual(self.queue.delayed_length(), 1)
        self.assertEqual(self.queue.length("default"), 0)

        # 2. Promote due jobs
        promoted = self.queue.promote_due_jobs()
        self.assertEqual(promoted, 1)
        self.assertEqual(self.queue.delayed_length(), 0)
        self.assertEqual(self.queue.length("default"), 1)

        # 3. Dequeue from active list
        q_name, job_id = self.queue.dequeue("default", timeout=1)
        self.assertEqual(job_id, "delayed-job-123")


class WorkerRetryAndBackoffExecutionTests(TestCase):
    def setUp(self):
        from apps.core.redis_client import get_redis_client
        from apps.jobs.queue import RedisJobQueue
        self.redis = get_redis_client()
        self.queue = RedisJobQueue(key_prefix="test_worker_retries")
        self.queue.clear("default")
        self.queue.clear_delayed()

        self.org = Organization.objects.create(name='Retry Org', slug='retry-org')
        from apps.jobs.worker import CustomWorker
        self.worker = CustomWorker(
            queues=["default"],
            timeout=1,
            worker_id="retry-worker-001",
            queue_instance=self.queue,
        )

    def tearDown(self):
        self.queue.clear("default")
        self.queue.clear_delayed()

    def test_worker_retries_flaky_task_and_succeeds_eventually(self):
        # Flaky task configured to fail 2 times with 503, then succeed on 3rd attempt
        task_key = "flaky_test_job_1"
        self.redis.delete(f"forgeflow:task:flaky:{task_key}")

        job = Job.objects.create(
            organization=self.org,
            name='flaky-payment-sync',
            type='flaky_service',
            payload={'key': task_key, 'fail_times': 2},
            status=JobStatus.QUEUED,
            queue='default',
            max_retries=3,
            backoff_base=2,
        )
        self.queue.enqueue("default", str(job.id))

        # --- Attempt #1 (Fails -> Schedules Retry #1 with 2s delay) ---
        self.worker.process_job(str(job.id), "default")
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.RETRYING)
        self.assertEqual(job.retry_count, 1)
        self.assertIsNotNone(job.next_retry_at)
        self.assertEqual(job.attempts.count(), 1)
        self.assertEqual(job.attempts.first().status, AttemptStatus.FAILED)
        self.assertEqual(self.queue.delayed_length(), 1)

        # Fast-forward / promote delayed job to active queue
        self.queue.promote_due_jobs()
        # If delayed by >0 seconds, force promote by setting score <= now
        self.redis.zadd(self.queue.get_delayed_key(), {f"default:{job.id}": 0})
        self.queue.promote_due_jobs()

        # --- Attempt #2 (Fails -> Schedules Retry #2 with 4s delay) ---
        self.worker.process_job(str(job.id), "default")
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.RETRYING)
        self.assertEqual(job.retry_count, 2)
        self.assertEqual(job.attempts.count(), 2)

        # Fast-forward / promote delayed job to active queue
        self.redis.zadd(self.queue.get_delayed_key(), {f"default:{job.id}": 0})
        self.queue.promote_due_jobs()

        # --- Attempt #3 (Succeeds!) ---
        self.worker.process_job(str(job.id), "default")
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.SUCCESS)
        self.assertEqual(job.attempts.count(), 3)
        self.assertEqual(job.attempts.last().status, AttemptStatus.SUCCESS)
        self.assertIsNone(job.error)
        self.assertIsNone(job.next_retry_at)
        self.assertEqual(job.result['status'], 'success')
        self.assertEqual(job.result['recovered_after_attempts'], 3)

    def test_worker_fails_non_retryable_task_immediately_with_zero_retries(self):
        # Non-retryable permanent error (e.g. InvalidPayloadError)
        job = Job.objects.create(
            organization=self.org,
            name='invalid-payload-job',
            type='permanent_fail',
            payload={'error_message': 'Missing mandatory auth token'},
            status=JobStatus.QUEUED,
            queue='default',
            max_retries=3,
        )
        self.queue.enqueue("default", str(job.id))

        self.worker.process_job(str(job.id), "default")
        job.refresh_from_db()

        # Must fail immediately without entering RETRYING state
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertEqual(job.retry_count, 0)
        self.assertIsNone(job.next_retry_at)
        self.assertEqual(job.attempts.count(), 1)
        self.assertEqual(job.attempts.first().status, AttemptStatus.FAILED)
        self.assertIn("Missing mandatory auth token", job.error)
        # No items scheduled in delayed queue
        self.assertEqual(self.queue.delayed_length(), 0)

    def test_worker_exhausts_max_retries_and_marks_failed(self):
        task_key = "exhaust_retries_job"
        self.redis.delete(f"forgeflow:task:flaky:{task_key}")

        # Set task to fail 10 times, but max_retries = 2
        job = Job.objects.create(
            organization=self.org,
            name='exhaust-retries-test',
            type='flaky_service',
            payload={'key': task_key, 'fail_times': 10},
            status=JobStatus.QUEUED,
            queue='default',
            max_retries=2,
            backoff_base=2,
        )

        # Attempt 1 -> Fails, retry_count becomes 1, status = RETRYING
        self.worker.process_job(str(job.id), "default")
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.RETRYING)
        self.assertEqual(job.retry_count, 1)

        # Attempt 2 -> Fails, retry_count becomes 2, status = RETRYING
        self.redis.zadd(self.queue.get_delayed_key(), {f"default:{job.id}": 0})
        self.queue.promote_due_jobs()
        self.worker.process_job(str(job.id), "default")
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.RETRYING)
        self.assertEqual(job.retry_count, 2)

        # Attempt 3 -> Fails, max_retries (2) exceeded -> status = FAILED
        self.redis.zadd(self.queue.get_delayed_key(), {f"default:{job.id}": 0})
        self.queue.promote_due_jobs()
        self.worker.process_job(str(job.id), "default")
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertEqual(job.retry_count, 2)
        self.assertEqual(job.attempts.count(), 3)
        self.assertIsNotNone(job.completed_at)
        self.assertEqual(self.queue.delayed_length(), 0)
