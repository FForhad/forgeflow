from django.urls import path
from apps.jobs.views import (
    JobCancelView,
    JobDetailView,
    JobEnqueueView,
    JobListCreateView,
    JobRootCancelView,
    JobRootDetailView,
    JobRootEnqueueView,
    JobRootListCreateView,
)

# Top-level jobs patterns: /api/v1/jobs/
urlpatterns = [
    path('', JobRootListCreateView.as_view(), name='job-list'),
    path('<uuid:pk>/', JobRootDetailView.as_view(), name='job-detail'),
    path('<uuid:pk>/enqueue/', JobRootEnqueueView.as_view(), name='job-enqueue'),
    path('<uuid:pk>/cancel/', JobRootCancelView.as_view(), name='job-cancel'),
]

# Nested patterns for orgs: /api/v1/organizations/{org_id}/jobs/
scoped_urlpatterns = [
    path('', JobListCreateView.as_view(), name='org-job-list-create'),
    path('<uuid:pk>/', JobDetailView.as_view(), name='org-job-detail'),
    path('<uuid:pk>/enqueue/', JobEnqueueView.as_view(), name='org-job-enqueue'),
    path('<uuid:pk>/cancel/', JobCancelView.as_view(), name='org-job-cancel'),
]
