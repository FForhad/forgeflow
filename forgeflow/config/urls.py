"""
URL configuration for ForgeFlow project.
"""

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from apps.jobs.urls import scoped_urlpatterns as org_job_urls

urlpatterns = [
    path('admin/', admin.site.urls),

    # OpenAPI Schema & Interactive Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # Core & Health
    path('api/v1/', include('apps.core.urls')),

    # Auth & Accounts
    path('api/v1/auth/', include('apps.accounts.urls')),

    # Organizations & RBAC
    path('api/v1/organizations/', include('apps.organizations.urls')),
    path('api/v1/organizations/<uuid:organization_id>/jobs/', include((org_job_urls, 'org-jobs'))),

    # Direct Job REST API
    path('api/v1/jobs/', include('apps.jobs.urls')),
]
