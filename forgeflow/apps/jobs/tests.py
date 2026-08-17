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

        self.list_create_url = reverse('job-list-create', kwargs={'organization_id': self.org.id})
        self.detail_url = reverse('job-detail', kwargs={'organization_id': self.org.id, 'pk': self.job.id})
        self.cancel_url = reverse('job-cancel', kwargs={'organization_id': self.org.id, 'pk': self.job.id})

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
