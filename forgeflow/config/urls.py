"""
URL configuration for ForgeFlow project.
"""

from django.contrib import admin
from django.urls import include, path

from apps.jobs.urls import scoped_urlpatterns as org_job_urls

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('apps.core.urls')),
    path('api/v1/auth/', include('apps.accounts.urls')),
    path('api/v1/organizations/', include('apps.organizations.urls')),
    path('api/v1/organizations/<uuid:organization_id>/jobs/', include((org_job_urls, 'org-jobs'))),
    path('api/v1/jobs/', include('apps.jobs.urls')),
]
