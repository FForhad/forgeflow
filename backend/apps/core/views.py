import logging
from django.db import DatabaseError, OperationalError, connection
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)


class HealthResponseSerializer(serializers.Serializer):
    status = serializers.CharField(default="ok")


class DatabaseHealthResponseSerializer(serializers.Serializer):
    status = serializers.CharField(default="ok")
    database = serializers.CharField(default="connected")


class HealthCheckView(APIView):
    """
    Basic application health check to verify service availability.
    """
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        tags=['Health'],
        summary='Basic Health Check',
        responses={200: HealthResponseSerializer},
    )
    def get(self, request, *args, **kwargs):
        return Response({"status": "ok"}, status=status.HTTP_200_OK)


class DatabaseHealthCheckView(APIView):
    """
    Database health check verifying real connection with a test query.
    Returns 200 with database: connected if DB is reachable, or 503 if unreachable.
    """
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        tags=['Health'],
        summary='Database Health Check',
        responses={
            200: DatabaseHealthResponseSerializer,
            503: OpenApiResponse(description="Database disconnected"),
        },
    )
    def get(self, request, *args, **kwargs):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1;")
                cursor.fetchone()
            return Response(
                {
                    "status": "ok",
                    "database": "connected",
                },
                status=status.HTTP_200_OK,
            )
        except (OperationalError, DatabaseError, Exception) as exc:
            logger.error(f"Database health check failed: {exc}")
            return Response(
                {
                    "status": "unavailable",
                    "database": "disconnected",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
