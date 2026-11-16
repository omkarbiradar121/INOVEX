import os
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, Http404, JsonResponse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.core.exceptions import ValidationError, PermissionDenied
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions

from accounts.permissions import role_required, IsSupervisorUser, IsEngineerUser
from accounts.models import UserRole
from inspections.models import Inspection
from .models import QualityIncident, IncidentAction, IncidentReview, ProductSOPMapping
from .serializers import (
    QualityIncidentListSerializer,
    QualityIncidentDetailSerializer,
    IncidentActionSerializer,
    IncidentReviewSerializer,
    IncidentCreateSerializer,
    ReviewSubmissionSerializer,
    ProductSOPMappingSerializer
)
from .services.incident_engine import get_or_create_quality_incident
from .services.review_service import submit_incident_review
from .services.sop_service import get_sop_absolute_path, check_product_sop_availability
from .services.mapping_service import get_product_sop_mappings
from .services.pdf_report import build_incident_pdf


# ==========================================
# WEB TEMPLATE VIEWS
# ==========================================

@login_required
def incident_list_view(request):
    """
    Main Quality Incident dashboard for Engineer, Supervisor, and Admin.
    """
    user = request.user
    role = getattr(user, 'role', '').lower()

    # Search & filters
    search_q = request.GET.get('q', '').strip()
    evidence_filter = request.GET.get('evidence_status', '').strip()
    review_filter = request.GET.get('review_status', '').strip()
    product_filter = request.GET.get('product', '').strip()

    incidents_qs = QualityIncident.objects.select_related('inspection', 'product', 'created_by')

    # Role barrier for viewing incidents:
    if role == 'engineer':
        # Engineers view their own incidents
        incidents_qs = incidents_qs.filter(created_by=user)
    # Supervisors and Admins can view all incidents

    if search_q:
        incidents_qs = incidents_qs.filter(
            Q(incident_id__icontains=search_q) |
            Q(product__product_id__icontains=search_q) |
            Q(product__name__icontains=search_q) |
            Q(inspection__id__icontains=search_q)
        )
    if evidence_filter in ['Sufficient', 'Insufficient']:
        incidents_qs = incidents_qs.filter(evidence_status=evidence_filter)
    if review_filter in ['Pending', 'Approved for follow-up', 'Needs more information']:
        incidents_qs = incidents_qs.filter(review_status=review_filter)
    if product_filter:
        incidents_qs = incidents_qs.filter(product__product_id=product_filter)

    # For Engineers: fetch eligible inspections for incident creation
    eligible_inspections = []
    if role == 'engineer':
        base_eligible = Inspection.objects.filter(
            engineer=user,
            status__iexact='completed',
            predicted_class__iexact='defective'
        ).select_related('product').order_by('-created_at')
        
        # Attach existing incident info if any
        existing_incident_map = {
            qi.inspection_id: qi.incident_id
            for qi in QualityIncident.objects.filter(inspection__in=base_eligible)
        }
        for ins in base_eligible:
            eligible_inspections.append({
                'inspection': ins,
                'has_incident': ins.id in existing_incident_map,
                'incident_id': existing_incident_map.get(ins.id)
            })

    # Stats
    total_count = QualityIncident.objects.count() if role != 'engineer' else incidents_qs.count()
    pending_count = QualityIncident.objects.filter(review_status='Pending').count()
    insufficient_count = QualityIncident.objects.filter(evidence_status='Insufficient').count()
    approved_count = QualityIncident.objects.filter(review_status='Approved for follow-up').count()

    context = {
        'incidents': incidents_qs,
        'eligible_inspections': eligible_inspections,
        'search_q': search_q,
        'evidence_filter': evidence_filter,
        'review_filter': review_filter,
        'product_filter': product_filter,
        'stats': {
            'total': total_count,
            'pending': pending_count,
            'insufficient': insufficient_count,
            'approved': approved_count,
        },
        'user_role': role,
    }
    return render(request, 'incidents/incident_list.html', context)


@login_required
@require_http_methods(["POST"])
def incident_create_view(request):
    """
    POST view for Engineer to create or retrieve an incident from an eligible inspection.
    """
    inspection_id = request.POST.get('inspection_id')
    if not inspection_id:
        messages.error(request, "Missing inspection ID.")
        return redirect('incidents:incident_list')

    inspection = get_object_or_404(Inspection, id=inspection_id)

    try:
        incident, created = get_or_create_quality_incident(inspection, request.user)
        if created:
            messages.success(request, f"Quality Incident {incident.incident_id} successfully created.")
        else:
            messages.info(request, f"Quality Incident {incident.incident_id} already exists for this inspection.")
        return redirect('incidents:incident_detail', incident_id=incident.incident_id)
    except ValidationError as e:
        messages.error(request, str(e))
        return redirect('incidents:incident_list')
    except PermissionDenied as e:
        messages.error(request, str(e))
        return redirect('incidents:incident_list')


@login_required
def incident_detail_view(request, incident_id):
    """
    Detailed incident view organized into clear sections:
    Overview, Workflow Progress Tracker, Inspection Details, AI Analysis, SOP Evidence & Coverage, Supervisor Review.
    """
    incident = get_object_or_404(
        QualityIncident.objects.select_related('inspection', 'product', 'created_by'),
        incident_id=incident_id
    )

    # Permission check: Engineers can only view their own incidents
    user = request.user
    role = getattr(user, 'role', '').lower()
    if role == 'engineer' and incident.created_by_id != user.id:
        context = {
            'required_roles': ['Supervisor', 'Administrator', 'Incident Owner'],
            'user_role': user.get_role_display() if hasattr(user, 'get_role_display') else role,
        }
        return render(request, 'accounts/access_denied.html', context, status=403)

    # SOP Coverage Information
    mappings = list(get_product_sop_mappings(incident.product.product_id))
    coverage_items = []
    for m in mappings:
        pdf_path = get_sop_absolute_path(m.pdf_filename)
        exists = os.path.isfile(pdf_path)
        coverage_items.append({
            'document_id': m.sop_document_id,
            'revision': m.revision,
            'filename': m.pdf_filename,
            'required': m.required,
            'available': exists,
        })

    # Workflow stage calculation:
    # 1. Inspection Flagged (done)
    # 2. Incident Created (done)
    # 3. SOP Evidence Retrieved (done if sufficient)
    # 4. Actions Generated (done if actions exist)
    # 5. Supervisor Review Pending (active if pending)
    # 6. Review Completed (done if approved or needs info)
    actions = list(incident.actions.all())
    reviews = list(incident.reviews.all())

    stages = [
        {'name': 'Defect Detected', 'status': 'completed', 'desc': f'Inspection #{incident.inspection.id} flagged Defective'},
        {'name': 'Incident Created', 'status': 'completed', 'desc': incident.incident_id},
        {
            'name': 'SOP Retrieval',
            'status': 'completed' if incident.evidence_status == 'Sufficient' else 'warning',
            'desc': 'Validated' if incident.evidence_status == 'Sufficient' else 'Insufficient Evidence'
        },
        {
            'name': 'Action Synthesis',
            'status': 'completed' if actions else ('warning' if incident.evidence_status == 'Insufficient' else 'pending'),
            'desc': f'{len(actions)} Evidence Actions' if actions else 'Manual Review Required'
        },
        {
            'name': 'Supervisor Review',
            'status': 'completed' if incident.review_status != 'Pending' else 'active',
            'desc': incident.review_status
        }
    ]

    context = {
        'incident': incident,
        'actions': actions,
        'reviews': reviews,
        'coverage_items': coverage_items,
        'stages': stages,
        'user_role': role,
        'can_review': role == 'supervisor',
    }
    return render(request, 'incidents/incident_detail.html', context)


@login_required
@require_http_methods(["POST"])
def incident_review_view(request, incident_id):
    """
    Submits a formal Supervisor review decision.
    """
    incident = get_object_or_404(QualityIncident, incident_id=incident_id)
    decision = request.POST.get('decision', '').strip()
    comment = request.POST.get('comment', '').strip()

    try:
        review = submit_incident_review(incident, request.user, decision, comment)
        messages.success(request, f"Review decision '{review.decision}' recorded successfully.")
    except (ValidationError, PermissionDenied) as e:
        messages.error(request, str(e))

    return redirect('incidents:incident_detail', incident_id=incident.incident_id)


@login_required
def sop_evidence_viewer_view(request):
    """
    Interactive SOP Evidence Viewer.
    Opens document, navigates to cited page, and highlights passage.
    """
    doc_id = request.GET.get('doc_id', '').strip()
    page_num = request.GET.get('page', '1').strip()
    passage = request.GET.get('passage', '').strip()
    incident_id = request.GET.get('incident_id', '').strip()

    mapping = ProductSOPMapping.objects.filter(sop_document_id=doc_id).first()
    if not mapping:
        raise Http404(f"SOP Document {doc_id} not recognized.")

    pdf_path = get_sop_absolute_path(mapping.pdf_filename)
    if not os.path.isfile(pdf_path):
        raise Http404(f"SOP PDF file {mapping.pdf_filename} not found on server.")

    context = {
        'doc_id': doc_id,
        'doc_name': mapping.product_name,
        'revision': mapping.revision,
        'filename': mapping.pdf_filename,
        'page_num': page_num,
        'passage': passage,
        'incident_id': incident_id,
    }
    return render(request, 'incidents/sop_viewer.html', context)


@login_required
def serve_sop_pdf_view(request, filename):
    """
    Serves the actual SOP PDF inline with correct Content-Type for the viewer.
    """
    # Sanitize filename
    clean_filename = os.path.basename(filename)
    pdf_path = get_sop_absolute_path(clean_filename)

    if not os.path.isfile(pdf_path):
        raise Http404("Requested SOP file does not exist.")

    with open(pdf_path, 'rb') as f:
        pdf_bytes = f.read()

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="{clean_filename}"'
    return response


@login_required
def incident_export_pdf_view(request, incident_id):
    """
    Exports a professional INOVEX Quality Incident Report in PDF format.
    """
    incident = get_object_or_404(
        QualityIncident.objects.select_related('inspection', 'product', 'created_by'),
        incident_id=incident_id
    )

    # Permission check for export:
    user = request.user
    role = getattr(user, 'role', '').lower()
    if role == 'engineer' and incident.created_by_id != user.id:
        return HttpResponse("Unauthorized to export this incident report.", status=403)

    pdf_bytes = build_incident_pdf(incident)
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Quality_Incident_{incident.incident_id}.pdf"'
    return response


# ==========================================
# REST API VIEWS
# ==========================================

class EligibleInspectionsAPIView(APIView):
    """
    API: Returns completed Defective inspections eligible for incident creation.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        role = getattr(user, 'role', '').lower()

        qs = Inspection.objects.filter(status__iexact='completed', predicted_class__iexact='defective').select_related('product')
        if role == 'engineer':
            qs = qs.filter(engineer=user)

        data = []
        existing_incident_map = {
            qi.inspection_id: qi.incident_id
            for qi in QualityIncident.objects.filter(inspection__in=qs)
        }
        for ins in qs.order_by('-created_at'):
            data.append({
                'inspection_id': ins.id,
                'product_id': ins.product.product_id,
                'product_name': ins.product.name,
                'prediction': ins.predicted_class,
                'confidence': ins.confidence,
                'model_version': getattr(ins, 'model_version', 'BIT-PLATE-CV-1.0'),
                'created_at': ins.created_at,
                'has_incident': ins.id in existing_incident_map,
                'incident_id': existing_incident_map.get(ins.id),
            })
        return Response(data, status=status.HTTP_200_OK)


class IncidentListCreateAPIView(APIView):
    """
    API: List incidents or Create a new incident.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        role = getattr(user, 'role', '').lower()

        qs = QualityIncident.objects.select_related('inspection', 'product', 'created_by')
        if role == 'engineer':
            qs = qs.filter(created_by=user)

        # Filters
        search_q = request.query_params.get('search')
        if search_q:
            qs = qs.filter(
                Q(incident_id__icontains=search_q) |
                Q(product__product_id__icontains=search_q) |
                Q(inspection__id__icontains=search_q)
            )
        evidence_status = request.query_params.get('evidence_status')
        if evidence_status:
            qs = qs.filter(evidence_status=evidence_status)
        review_status = request.query_params.get('review_status')
        if review_status:
            qs = qs.filter(review_status=review_status)

        serializer = QualityIncidentListSerializer(qs.order_by('-created_at'), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = IncidentCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        inspection_id = serializer.validated_data['inspection_id']
        try:
            inspection = Inspection.objects.get(id=inspection_id)
        except Inspection.DoesNotExist:
            return Response({'error': f"Inspection #{inspection_id} does not exist."}, status=status.HTTP_404_NOT_FOUND)

        try:
            incident, created = get_or_create_quality_incident(inspection, request.user)
            out_serializer = QualityIncidentDetailSerializer(incident)
            status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
            return Response(out_serializer.data, status=status_code)
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionDenied as e:
            return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)


class IncidentDetailAPIView(APIView):
    """
    API: Retrieve full incident details.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, incident_id):
        try:
            incident = QualityIncident.objects.select_related('inspection', 'product', 'created_by').get(incident_id=incident_id)
        except QualityIncident.DoesNotExist:
            return Response({'error': f"Incident {incident_id} not found."}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        role = getattr(user, 'role', '').lower()
        if role == 'engineer' and incident.created_by_id != user.id:
            return Response({'error': "Permission denied: you can only access your own incidents."}, status=status.HTTP_403_FORBIDDEN)

        serializer = QualityIncidentDetailSerializer(incident)
        return Response(serializer.data, status=status.HTTP_200_OK)


class IncidentReviewAPIView(APIView):
    """
    API: Submit Supervisor Review decision.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, incident_id):
        try:
            incident = QualityIncident.objects.get(incident_id=incident_id)
        except QualityIncident.DoesNotExist:
            return Response({'error': f"Incident {incident_id} not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = ReviewSubmissionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        decision = serializer.validated_data['decision']
        comment = serializer.validated_data['comment']

        try:
            review = submit_incident_review(incident, request.user, decision, comment)
            return Response(IncidentReviewSerializer(review).data, status=status.HTTP_201_CREATED)
        except PermissionDenied as e:
            return Response({'error': str(e)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class IncidentPDFExportAPIView(APIView):
    """
    API: Stream Incident PDF Report.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, incident_id):
        try:
            incident = QualityIncident.objects.select_related('inspection', 'product', 'created_by').get(incident_id=incident_id)
        except QualityIncident.DoesNotExist:
            return Response({'error': f"Incident {incident_id} not found."}, status=status.HTTP_404_NOT_FOUND)

        user = request.user
        role = getattr(user, 'role', '').lower()
        if role == 'engineer' and incident.created_by_id != user.id:
            return Response({'error': "Permission denied to export this incident."}, status=status.HTTP_403_FORBIDDEN)

        pdf_bytes = build_incident_pdf(incident)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="Quality_Incident_{incident.incident_id}.pdf"'
        return response
