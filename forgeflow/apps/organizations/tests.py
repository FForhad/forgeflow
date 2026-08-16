from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError
from django.test import TestCase
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
