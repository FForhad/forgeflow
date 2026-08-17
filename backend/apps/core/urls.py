from django.urls import path
from apps.core.views import DatabaseHealthCheckView, HealthCheckView

urlpatterns = [
    path('health/', HealthCheckView.as_view(), name='health-check'),
    path('health/database/', DatabaseHealthCheckView.as_view(), name='database-health-check'),
]
