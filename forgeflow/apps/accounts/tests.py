from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError
from django.test import TestCase

User = get_user_model()


class UserModelTests(TestCase):
    def test_create_user_successful(self):
        user = User.objects.create_user(
            email='engineer@forgeflow.dev',
            password='SecurePassword123!',
            first_name='Lead',
            last_name='Engineer',
        )
        self.assertEqual(user.email, 'engineer@forgeflow.dev')
        self.assertTrue(user.check_password('SecurePassword123!'))
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)

    def test_create_user_without_email_raises_error(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email='', password='password123')

    def test_duplicate_email_raises_integrity_error(self):
        User.objects.create_user(email='unique@forgeflow.dev', password='password123')
        with self.assertRaises(IntegrityError):
            User.objects.create_user(email='unique@forgeflow.dev', password='password456')
