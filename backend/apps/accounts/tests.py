import datetime
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError
from django.test import TestCase
from django.urls import reverse
import jwt
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

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


class AuthAPITests(APITestCase):
    def setUp(self):
        self.register_url = reverse('auth-register')
        self.login_url = reverse('auth-login')
        self.refresh_url = reverse('auth-refresh')
        self.logout_url = reverse('auth-logout')
        self.me_url = reverse('auth-me')

        self.user_data = {
            'email': 'developer@forgeflow.dev',
            'password': 'StrongPassword123!',
            'first_name': 'Dev',
            'last_name': 'One',
        }

    # ==========================================
    # 1. Happy Path Flow Tests
    # ==========================================

    def test_register_success(self):
        response = self.client.post(self.register_url, self.user_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('access', response.json())
        self.assertIn('refresh', response.json())
        self.assertEqual(response.json()['user']['email'], self.user_data['email'])

        user = User.objects.get(email=self.user_data['email'])
        self.assertTrue(user.check_password(self.user_data['password']))

    def test_login_success(self):
        User.objects.create_user(**self.user_data)
        response = self.client.post(
            self.login_url,
            {
                'email': self.user_data['email'],
                'password': self.user_data['password'],
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.json())
        self.assertIn('refresh', response.json())
        self.assertEqual(response.json()['user']['email'], self.user_data['email'])

    def test_refresh_token_lifecycle(self):
        user = User.objects.create_user(**self.user_data)
        refresh = RefreshToken.for_user(user)

        response = self.client.post(self.refresh_url, {'refresh': str(refresh)}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.json())

    def test_authenticated_protected_endpoint(self):
        user = User.objects.create_user(**self.user_data)
        access_token = str(AccessToken.for_user(user))

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['email'], user.email)

    def test_logout_and_blacklist(self):
        user = User.objects.create_user(**self.user_data)
        refresh = RefreshToken.for_user(user)

        # Logout by blacklisting refresh token
        logout_response = self.client.post(self.logout_url, {'refresh': str(refresh)}, format='json')
        self.assertEqual(logout_response.status_code, status.HTTP_200_OK)

        # Attempting to refresh with the blacklisted token must fail with 401
        refresh_response = self.client.post(self.refresh_url, {'refresh': str(refresh)}, format='json')
        self.assertEqual(refresh_response.status_code, status.HTTP_401_UNAUTHORIZED)

    # ==========================================
    # 2. Failure Mode / Security / "Break It" Tests
    # ==========================================

    def test_register_duplicate_email_fails(self):
        User.objects.create_user(**self.user_data)
        response = self.client.post(self.register_url, self.user_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('email', response.json())

    def test_register_weak_password_fails(self):
        weak_data = self.user_data.copy()
        weak_data['email'] = 'weak@forgeflow.dev'
        weak_data['password'] = '123'  # Too short, fails Django validators
        response = self.client.post(self.register_url, weak_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.json())

    def test_login_wrong_password_fails(self):
        User.objects.create_user(**self.user_data)
        response = self.client.post(
            self.login_url,
            {
                'email': self.user_data['email'],
                'password': 'WrongPassword123!',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_protected_endpoint_missing_token_fails(self):
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_protected_endpoint_malformed_token_fails(self):
        self.client.credentials(HTTP_AUTHORIZATION='Bearer this-is-not-a-valid-jwt-token')
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_protected_endpoint_wrong_signature_fails(self):
        user = User.objects.create_user(**self.user_data)
        payload = {
            'user_id': str(user.id),
            'exp': datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=15),
            'token_type': 'access',
        }
        tampered_token = jwt.encode(payload, 'wrong-secret-key-that-is-at-least-32-bytes-long', algorithm='HS256')

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {tampered_token}')
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_protected_endpoint_expired_token_fails(self):
        user = User.objects.create_user(**self.user_data)
        payload = {
            'user_id': str(user.id),
            'exp': datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=10),
            'token_type': 'access',
        }
        expired_token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {expired_token}')
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
