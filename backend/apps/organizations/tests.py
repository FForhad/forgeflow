from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from apps.organizations.models import APIKey, Membership, MembershipRole, Organization, Team

User = get_user_model()


class OrganizationModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='orgowner@forgeflow.dev',
            password='StrongPassword123!',
        )
        self.org = Organization.objects.create(
            name='Acme Corp',
            slug='acme-corp',
        )

    def test_create_organization(self):
        self.assertEqual(str(self.org), 'Acme Corp')
        self.assertEqual(self.org.slug, 'acme-corp')

    def test_duplicate_slug_raises_integrity_error(self):
        with self.assertRaises(IntegrityError):
            Organization.objects.create(name='Acme Copy', slug='acme-corp')

    def test_create_membership_with_role(self):
        membership = Membership.objects.create(
            user=self.user,
            organization=self.org,
            role=MembershipRole.OWNER,
        )
        self.assertEqual(membership.role, MembershipRole.OWNER)
        self.assertIn(membership, self.org.memberships.all())

    def test_duplicate_user_org_membership_raises_error(self):
        Membership.objects.create(
            user=self.user,
            organization=self.org,
            role=MembershipRole.OWNER,
        )
        with self.assertRaises(IntegrityError):
            Membership.objects.create(
                user=self.user,
                organization=self.org,
                role=MembershipRole.DEVELOPER,
            )

    def test_create_team_and_api_key(self):
        team = Team.objects.create(organization=self.org, name='Platform Engineering')
        api_key = APIKey.objects.create(
            organization=self.org,
            name='Production Ingestion Key',
            key_prefix='ff_live_',
            hashed_key='hashed_value_example',
        )
        self.assertEqual(str(team), 'Acme Corp / Platform Engineering')
        self.assertTrue(api_key.is_active)


class OrganizationRBACAPITests(APITestCase):
    def setUp(self):
        # Create users for all 4 roles
        self.owner = User.objects.create_user(email='owner@acme.dev', password='Password123!')
        self.admin = User.objects.create_user(email='admin@acme.dev', password='Password123!')
        self.dev = User.objects.create_user(email='dev@acme.dev', password='Password123!')
        self.viewer = User.objects.create_user(email='viewer@acme.dev', password='Password123!')
        self.outsider = User.objects.create_user(email='outsider@other.dev', password='Password123!')

        # Create organization
        self.org = Organization.objects.create(name='Acme Corporation', slug='acme-corp')

        # Assign memberships
        Membership.objects.create(user=self.owner, organization=self.org, role=MembershipRole.OWNER)
        Membership.objects.create(user=self.admin, organization=self.org, role=MembershipRole.ADMIN)
        Membership.objects.create(user=self.dev, organization=self.org, role=MembershipRole.DEVELOPER)
        Membership.objects.create(user=self.viewer, organization=self.org, role=MembershipRole.VIEWER)

    def auth_as(self, user):
        token = str(AccessToken.for_user(user))
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_create_organization_creator_becomes_owner(self):
        self.auth_as(self.outsider)
        url = reverse('organization-list-create')
        response = self.client.post(url, {'name': 'New Tech Org'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        org_id = response.json()['id']
        membership = Membership.objects.filter(user=self.outsider, organization_id=org_id).first()
        self.assertIsNotNone(membership)
        self.assertEqual(membership.role, MembershipRole.OWNER)

    def test_tenant_isolation_list_organizations(self):
        self.auth_as(self.outsider)
        url = reverse('organization-list-create')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Outsider does not belong to Acme Corporation, should get empty list
        self.assertEqual(len(response.json()), 0)

        # Member should see Acme Corporation
        self.auth_as(self.viewer)
        response_viewer = self.client.get(url)
        self.assertEqual(response_viewer.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response_viewer.json()), 1)
        self.assertEqual(response_viewer.json()[0]['name'], 'Acme Corporation')

    def test_delete_organization_rbac(self):
        url = reverse('organization-detail', kwargs={'pk': self.org.id})

        # VIEWER cannot delete (403)
        self.auth_as(self.viewer)
        self.assertEqual(self.client.delete(url).status_code, status.HTTP_403_FORBIDDEN)

        # DEVELOPER cannot delete (403)
        self.auth_as(self.dev)
        self.assertEqual(self.client.delete(url).status_code, status.HTTP_403_FORBIDDEN)

        # ADMIN cannot delete (403)
        self.auth_as(self.admin)
        self.assertEqual(self.client.delete(url).status_code, status.HTTP_403_FORBIDDEN)

        # OWNER CAN delete (204)
        self.auth_as(self.owner)
        self.assertEqual(self.client.delete(url).status_code, status.HTTP_204_NO_CONTENT)

    def test_member_management_rbac(self):
        new_candidate = User.objects.create_user(email='newbie@acme.dev', password='Password123!')
        url = reverse('organization-members', kwargs={'organization_id': self.org.id})

        # VIEWER cannot invite/add members (403)
        self.auth_as(self.viewer)
        res_viewer = self.client.post(url, {'email': new_candidate.email, 'role': 'DEVELOPER'}, format='json')
        self.assertEqual(res_viewer.status_code, status.HTTP_403_FORBIDDEN)

        # DEVELOPER cannot invite/add members (403)
        self.auth_as(self.dev)
        res_dev = self.client.post(url, {'email': new_candidate.email, 'role': 'DEVELOPER'}, format='json')
        self.assertEqual(res_dev.status_code, status.HTTP_403_FORBIDDEN)

        # ADMIN CAN invite/add members (201)
        self.auth_as(self.admin)
        res_admin = self.client.post(url, {'email': new_candidate.email, 'role': 'DEVELOPER'}, format='json')
        self.assertEqual(res_admin.status_code, status.HTTP_201_CREATED)
