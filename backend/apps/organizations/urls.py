from django.urls import path
from apps.organizations.views import (
    MemberDetailView,
    MemberListCreateView,
    OrganizationDetailView,
    OrganizationListCreateView,
)

urlpatterns = [
    path('', OrganizationListCreateView.as_view(), name='organization-list-create'),
    path('<uuid:pk>/', OrganizationDetailView.as_view(), name='organization-detail'),
    path('<uuid:organization_id>/members/', MemberListCreateView.as_view(), name='organization-members'),
    path('<uuid:organization_id>/members/<uuid:pk>/', MemberDetailView.as_view(), name='organization-member-detail'),
]
