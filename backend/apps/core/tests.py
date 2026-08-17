from unittest.mock import patch
from django.db.utils import OperationalError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class HealthCheckAPITest(APITestCase):
    def test_basic_health_check_returns_200_and_status_ok(self):
        url = reverse('health-check')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_database_health_check_returns_200_when_db_connected(self):
        url = reverse('database-health-check')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "database": "connected",
            },
        )

    @patch('apps.core.views.connection.cursor')
    def test_database_health_check_returns_503_when_db_disconnected(self, mock_cursor):
        mock_cursor.side_effect = OperationalError("DB connection refused")
        url = reverse('database-health-check')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(
            response.json(),
            {
                "status": "unavailable",
                "database": "disconnected",
            },
        )

    @patch('apps.core.redis_client.check_redis_connection', return_value=True)
    def test_redis_health_check_returns_200_when_connected(self, mock_check):
        url = reverse('redis-health-check')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "redis": "connected",
            },
        )

    @patch('apps.core.redis_client.check_redis_connection', return_value=False)
    def test_redis_health_check_returns_503_when_disconnected(self, mock_check):
        url = reverse('redis-health-check')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(
            response.json(),
            {
                "status": "unavailable",
                "redis": "disconnected",
            },
        )
