from django.urls import path
from . import views

app_name = 'incidents'

urlpatterns = [
    # Web UI Views
    path('', views.incident_list_view, name='incident_list'),
    path('create/', views.incident_create_view, name='incident_create'),
    path('viewer/sop/', views.sop_evidence_viewer_view, name='sop_viewer'),
    path('sops/file/<str:filename>/', views.serve_sop_pdf_view, name='serve_sop_pdf'),
    path('<str:incident_id>/', views.incident_detail_view, name='incident_detail'),
    path('<str:incident_id>/review/', views.incident_review_view, name='incident_review'),
    path('<str:incident_id>/pdf/', views.incident_export_pdf_view, name='incident_pdf'),

    # REST APIs
    path('api/eligible-inspections/', views.EligibleInspectionsAPIView.as_view(), name='api_eligible_inspections'),
    path('api/incidents/', views.IncidentListCreateAPIView.as_view(), name='api_incidents_list_create'),
    path('api/incidents/<str:incident_id>/', views.IncidentDetailAPIView.as_view(), name='api_incident_detail'),
    path('api/incidents/<str:incident_id>/review/', views.IncidentReviewAPIView.as_view(), name='api_incident_review'),
    path('api/incidents/<str:incident_id>/pdf/', views.IncidentPDFExportAPIView.as_view(), name='api_incident_pdf'),
]
