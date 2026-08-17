from django.urls import path
from apps.jobs.views import JobCancelView, JobDetailView, JobListCreateView

urlpatterns = [
    path('', JobListCreateView.as_view(), name='job-list-create'),
    path('<uuid:pk>/', JobDetailView.as_view(), name='job-detail'),
    path('<uuid:pk>/cancel/', JobCancelView.as_view(), name='job-cancel'),
]
