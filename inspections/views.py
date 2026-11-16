import time
from pathlib import Path
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.conf import settings
from rest_framework import generics, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response

from accounts.permissions import (
    engineer_required,
    supervisor_required,
    role_required,
    IsEngineerUser,
    IsSupervisorUser,
)
from accounts.models import UserRole
from products.models import Product
from .models import (
    Inspection,
    InspectionBatch,
    InspectionStatus,
    InspectionClass,
    SupervisorDecision,
    ModelEvaluationRun,
)
from .forms import (
    SingleInspectionForm,
    BatchInspectionForm,
    SupervisorReviewForm,
)
from .services import (
    get_model_service,
    ImageValidationService,
)
from .serializers import (
    InspectionSerializer,
    InspectionBatchSerializer,
    SupervisorReviewSerializer,
)
from .tasks import process_inspection_task


# ==============================================================================
# PHASE 5: SINGLE IMAGE INSPECTION WORKFLOW (ENGINEER)
# ==============================================================================

@engineer_required
def single_inspection_view(request):
    """
    Engineer single-image inspection interface:
    - Selects product P-PLATE01
    - Uploads single JPG/PNG image
    - Validates image content, size, and dimensions
    - Executes supplied pretrained classifier
    - Displays prediction, confidence, defect probability, model version
    - Persists record permanently in MySQL
    """
    if request.method == 'POST':
        form = SingleInspectionForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.cleaned_data['product']
            image_file = form.cleaned_data['image']
            metadata = getattr(image_file, 'validated_metadata', {})

            # 1. Create initial inspection record
            inspection = Inspection.objects.create(
                engineer=request.user,
                product=product,
                image=image_file,
                image_filename=image_file.name,
                file_size_bytes=metadata.get('file_size_bytes', image_file.size),
                image_width=metadata.get('image_width'),
                image_height=metadata.get('image_height'),
                image_format=metadata.get('image_format', ''),
                status=InspectionStatus.PROCESSING,
            )

            # 2. Run local pretrained vision classifier synchronously for instant feedback
            try:
                service = get_model_service()
                t0 = time.perf_counter()
                prediction = service.classify_image(inspection.image.path)
                t1 = time.perf_counter()

                inspection.predicted_class = prediction['predicted_class']
                inspection.confidence = prediction['confidence']
                inspection.defect_probability = prediction['defect_probability']
                inspection.model_version = prediction['model_version']
                inspection.inference_duration_ms = round((t1 - t0) * 1000, 2)
                inspection.status = InspectionStatus.COMPLETED
                inspection.completed_at = timezone.now()
                inspection.save()

                messages.success(request, f"Inspection completed: Classified as '{inspection.predicted_class}' with {inspection.confidence:.1%} confidence.")
                return redirect('inspection_result', pk=inspection.pk)

            except Exception as inference_err:
                inspection.status = InspectionStatus.FAILED
                inspection.failure_reason = f"Model execution error: {str(inference_err)}"
                inspection.completed_at = timezone.now()
                inspection.save()
                messages.error(request, f"Inference failed: {str(inference_err)}")
                return redirect('inspection_result', pk=inspection.pk)
        else:
            messages.error(request, "Please resolve the validation errors below.")
    else:
        # Pre-select P-PLATE01 by default
        default_prod = Product.objects.filter(product_id='P-PLATE01', is_active=True).first()
        initial = {'product': default_prod} if default_prod else {}
        form = SingleInspectionForm(initial=initial)

    context = {
        'form': form,
        'title': 'Single Product Inspection',
    }
    return render(request, 'inspections/single_inspection.html', context)


@role_required([UserRole.ENGINEER, UserRole.ADMIN, UserRole.SUPERVISOR])
def inspection_result_view(request, pk):
    """
    Displays the inspection result card:
    - Uploaded image preview
    - Predicted class: Normal or Defective
    - Confidence and defect probability
    - Model version: BIT-PLATE-CV-1.0
    - Technical validation specs
    Engineers see only their own inspections; Admins and Supervisors can inspect any record.
    """
    if request.user.is_engineer_role:
        inspection = get_object_or_404(Inspection, pk=pk, engineer=request.user)
    else:
        inspection = get_object_or_404(Inspection, pk=pk)
    context = {
        'inspection': inspection,
        'title': f"Inspection Result: {inspection.product.product_id}",
    }
    return render(request, 'inspections/inspection_result.html', context)


# ==============================================================================
# PHASE 6: BATCH IMAGE INSPECTION (CELERY & REDIS)
# ==============================================================================

@engineer_required
def batch_upload_view(request):
    """
    Accepts 1 to 10 images for asynchronous background batch processing.
    Each image is processed independently; one invalid image never halts others.
    """
    if request.method == 'POST':
        form = BatchInspectionForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.cleaned_data['product']
            files = request.FILES.getlist('images')

            if len(files) == 0:
                messages.error(request, "Please choose at least 1 image.")
                return render(request, 'inspections/batch_upload.html', {'form': form})
            if len(files) > 10:
                messages.error(request, f"Batch exceeds maximum limit of 10 images (selected: {len(files)}).")
                return render(request, 'inspections/batch_upload.html', {'form': form})

            # Create parent batch
            batch = InspectionBatch.objects.create(
                engineer=request.user,
                product=product,
                total_images=len(files),
                status=InspectionStatus.QUEUED,
            )

            # Create individual inspection records and dispatch Celery tasks
            for img_file in files:
                inspection = Inspection.objects.create(
                    batch=batch,
                    engineer=request.user,
                    product=product,
                    image=img_file,
                    image_filename=img_file.name,
                    file_size_bytes=img_file.size,
                    status=InspectionStatus.QUEUED,
                )
                process_inspection_task.delay(inspection.id)

            messages.success(request, f"Batch queued successfully with {len(files)} images for background analysis.")
            return redirect('batch_detail', batch_id=batch.batch_id)
        else:
            messages.error(request, "Please correct the form errors.")
    else:
        default_prod = Product.objects.filter(product_id='P-PLATE01', is_active=True).first()
        initial = {'product': default_prod} if default_prod else {}
        form = BatchInspectionForm(initial=initial)

    context = {
        'form': form,
        'title': 'Batch Inspection Intake',
    }
    return render(request, 'inspections/batch_upload.html', context)


@engineer_required
def batch_detail_view(request, batch_id):
    """
    Monitors real-time batch processing status (Queued, Processing, Completed, Failed).
    Shows detailed item cards with readable failure reasons.
    """
    batch = get_object_or_404(InspectionBatch, batch_id=batch_id, engineer=request.user)
    batch.refresh_batch_status()
    inspections = batch.inspections.all()

    context = {
        'batch': batch,
        'inspections': inspections,
        'title': f"Batch Status: {batch.batch_id[:8]}",
    }
    return render(request, 'inspections/batch_detail.html', context)


@engineer_required
def batch_status_api(request, batch_id):
    """
    REST API endpoint for polling real-time batch progress without full page reload.
    """
    batch = get_object_or_404(InspectionBatch, batch_id=batch_id, engineer=request.user)
    batch.refresh_batch_status()
    serializer = InspectionBatchSerializer(batch)
    return JsonResponse(serializer.data)


# ==============================================================================
# PHASE 7: INSPECTION HISTORY (ENGINEER)
# ==============================================================================

@engineer_required
def engineer_history_view(request):
    """
    Engineer-exclusive inspection history:
    - Strictly scoped to request.user (Engineers never view others' inspections)
    - Displays uploaded image thumbnail, product, original prediction, confidence, defect probability, model version, submission date/time, processing status
    """
    inspections = Inspection.objects.filter(engineer=request.user).select_related('product', 'batch').order_by('-created_at')

    # Optional status filter
    status_filter = request.GET.get('status')
    if status_filter in InspectionStatus.values:
        inspections = inspections.filter(status=status_filter)

    # Optional prediction filter
    prediction_filter = request.GET.get('prediction')
    if prediction_filter in InspectionClass.values:
        inspections = inspections.filter(predicted_class=prediction_filter)

    total_count = Inspection.objects.filter(engineer=request.user).count()
    completed_count = Inspection.objects.filter(engineer=request.user, status=InspectionStatus.COMPLETED).count()
    failed_count = Inspection.objects.filter(engineer=request.user, status=InspectionStatus.FAILED).count()
    normal_count = Inspection.objects.filter(engineer=request.user, predicted_class='Normal').count()
    defective_count = Inspection.objects.filter(engineer=request.user, predicted_class='Defective').count()

    context = {
        'inspections': inspections,
        'title': 'My Inspection History',
        'status_filter': status_filter or 'ALL',
        'prediction_filter': prediction_filter or 'ALL',
        'total_count': total_count,
        'completed_count': completed_count,
        'failed_count': failed_count,
        'normal_count': normal_count,
        'defective_count': defective_count,
    }
    return render(request, 'inspections/engineer_history.html', context)


# ==============================================================================
# PHASE 8: SUPERVISOR DASHBOARD & REVIEW WORKFLOW
# ==============================================================================

@supervisor_required
def supervisor_dashboard_view(request):
    """
    Supervisor oversight dashboard:
    - Organization-wide visibility across all submitted inspections
    - Filters by product, prediction (Normal, Defective) and review status (Pending, Confirmed, Corrected)
    - Displays original AI predictions alongside review states
    """
    inspections = Inspection.objects.select_related('product', 'engineer', 'reviewed_by').order_by('-created_at')

    # Filter by product
    prod_filter = request.GET.get('product')
    if prod_filter:
        inspections = inspections.filter(product__product_id=prod_filter)

    # Filter by prediction
    pred_filter = request.GET.get('prediction')
    if pred_filter in InspectionClass.values:
        inspections = inspections.filter(predicted_class=pred_filter)

    # Filter by review status
    review_filter = request.GET.get('review_status')
    if review_filter == 'PENDING':
        inspections = inspections.filter(status=InspectionStatus.COMPLETED, is_reviewed=False)
    elif review_filter == 'CONFIRMED':
        inspections = inspections.filter(supervisor_decision=SupervisorDecision.CONFIRMED)
    elif review_filter == 'CORRECTED':
        inspections = inspections.filter(
            supervisor_decision__in=[SupervisorDecision.CORRECTED_NORMAL, SupervisorDecision.CORRECTED_DEFECTIVE]
        )

    # Overview counters
    total_count = Inspection.objects.count()
    completed_count = Inspection.objects.filter(status=InspectionStatus.COMPLETED).count()
    reviewed_count = Inspection.objects.filter(is_reviewed=True).count()
    pending_review_count = Inspection.objects.filter(status=InspectionStatus.COMPLETED, is_reviewed=False).count()
    products = Product.objects.all()

    context = {
        'inspections': inspections,
        'products': products,
        'title': 'Supervisor Quality Review Portal',
        'prod_filter': prod_filter or 'ALL',
        'pred_filter': pred_filter or 'ALL',
        'review_filter': review_filter or 'ALL',
        'total_count': total_count,
        'completed_count': completed_count,
        'reviewed_count': reviewed_count,
        'pending_review_count': pending_review_count,
    }
    return render(request, 'inspections/supervisor_dashboard.html', context)


@supervisor_required
def supervisor_review_view(request, pk):
    """
    Review workflow for quality supervisors:
    - View uploaded image and original AI prediction/confidence
    - Confirm or correct predictions
    - Add optional review comments
    - Stores reviewer and timestamp
    - CRITICAL: Never overwrites original AI prediction or confidence fields!
    """
    inspection = get_object_or_404(Inspection, pk=pk)

    if request.method == 'POST':
        form = SupervisorReviewForm(request.POST)
        if form.is_valid():
            decision = form.cleaned_data['decision']
            notes = form.cleaned_data['notes']

            # Determine reviewed class while preserving original predicted_class
            if decision == SupervisorDecision.CONFIRMED:
                reviewed_class = inspection.predicted_class
            elif decision == SupervisorDecision.CORRECTED_NORMAL:
                reviewed_class = InspectionClass.NORMAL
            elif decision == SupervisorDecision.CORRECTED_DEFECTIVE:
                reviewed_class = InspectionClass.DEFECTIVE
            else:
                reviewed_class = inspection.predicted_class

            # Save review audit fields separately
            inspection.is_reviewed = True
            inspection.supervisor_decision = decision
            inspection.reviewed_class = reviewed_class
            inspection.supervisor_notes = notes
            inspection.reviewed_by = request.user
            inspection.reviewed_at = timezone.now()
            inspection.save(update_fields=[
                'is_reviewed',
                'supervisor_decision',
                'reviewed_class',
                'supervisor_notes',
                'reviewed_by',
                'reviewed_at',
            ])

            messages.success(request, f"Inspection {inspection.inspection_id[:8]} review recorded successfully ({decision}).")
            return redirect('supervisor_dashboard')
        else:
            messages.error(request, "Please correct the review form errors.")
    else:
        initial = {
            'decision': inspection.supervisor_decision or SupervisorDecision.CONFIRMED,
            'notes': inspection.supervisor_notes,
        }
        form = SupervisorReviewForm(initial=initial)

    context = {
        'inspection': inspection,
        'form': form,
        'title': f"Review Inspection {inspection.inspection_id[:8]}",
    }
    return render(request, 'inspections/supervisor_review.html', context)


# ==============================================================================
# PHASE 10: MODEL EVALUATION WORKFLOW (60 SAMPLES)
# ==============================================================================

@role_required([UserRole.ADMIN, UserRole.SUPERVISOR])
def model_evaluation_view(request):
    """
    Evaluates the supplied pretrained classifier on all 60 official sample images.
    Calculates TP, TN, FP, FN, Confusion Matrix, and Defect Recall.
    Uses original model predictions before any human review.
    """
    latest_run = ModelEvaluationRun.objects.first()

    context = {
        'latest_run': latest_run,
        'title': 'Model Performance Benchmark (60 Samples)',
    }
    return render(request, 'inspections/model_evaluation.html', context)


@role_required([UserRole.ADMIN, UserRole.SUPERVISOR])
@require_POST
def execute_model_evaluation_view(request):
    """
    Executes benchmark evaluation on the 60 samples from Samples/labels.csv.
    """
    import csv
    samples_dir = Path(settings.BASE_DIR) / 'Samples'
    labels_csv = samples_dir / 'labels.csv'

    if not labels_csv.exists():
        messages.error(request, "Samples/labels.csv not found in project directory.")
        return redirect('model_evaluation')

    service = get_model_service()

    tp = 0  # GT: Defective, Pred: Defective
    tn = 0  # GT: Normal, Pred: Normal
    fp = 0  # GT: Normal, Pred: Defective
    fn = 0  # GT: Defective, Pred: Normal
    failed = 0
    detailed_results = []

    with open(labels_csv, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            img_rel = row['relative_path']
            img_path = samples_dir / img_rel
            gt_label = row['label'].strip()

            try:
                res = service.classify_image(img_path)
                pred_label = res['predicted_class']
                conf = res['confidence']

                if gt_label == 'Defective' and pred_label == 'Defective':
                    tp += 1
                    match = True
                elif gt_label == 'Normal' and pred_label == 'Normal':
                    tn += 1
                    match = True
                elif gt_label == 'Normal' and pred_label == 'Defective':
                    fp += 1
                    match = False
                elif gt_label == 'Defective' and pred_label == 'Normal':
                    fn += 1
                    match = False
                else:
                    match = False

                detailed_results.append({
                    'image_id': row.get('image_id', img_rel),
                    'path': img_rel,
                    'ground_truth': gt_label,
                    'predicted': pred_label,
                    'confidence': conf,
                    'match': match,
                })
            except Exception as e:
                failed += 1
                detailed_results.append({
                    'image_id': row.get('image_id', img_rel),
                    'path': img_rel,
                    'ground_truth': gt_label,
                    'predicted': 'FAILED',
                    'error': str(e),
                    'match': False,
                })

    total_valid = tp + tn + fp + fn
    accuracy = (tp + tn) / total_valid if total_valid > 0 else 0.0
    defect_recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    defect_precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    f1 = (2 * defect_precision * defect_recall) / (defect_precision + defect_recall) if (defect_precision + defect_recall) > 0 else 0.0

    confusion_matrix = {
        'matrix': [[tn, fp], [fn, tp]],
        'labels': ['Normal', 'Defective'],
        'TN': tn,
        'FP': fp,
        'FN': fn,
        'TP': tp,
    }

    run = ModelEvaluationRun.objects.create(
        model_version=service.MODEL_NAME,
        total_samples=len(detailed_results),
        true_positives=tp,
        true_negatives=tn,
        false_positives=fp,
        false_negatives=fn,
        failed_predictions=failed,
        accuracy=round(accuracy, 4),
        defect_recall=round(defect_recall, 4),
        defect_precision=round(defect_precision, 4),
        f1_score=round(f1, 4),
        confusion_matrix_json=confusion_matrix,
        detailed_results_json=detailed_results,
        executed_by=request.user,
    )

    messages.success(request, f"Evaluation completed! Defect Recall: {run.defect_recall:.2%}, Accuracy: {run.accuracy:.2%}.")
    return redirect('model_evaluation')


# ==============================================================================
# REST APIS FOR INSPECTIONS & REVIEWS (ROLE-PROTECTED)
# ==============================================================================

class SingleInspectionAPIView(APIView):
    """
    REST API for single image upload & inspection (Engineer only).
    """
    permission_classes = [IsEngineerUser]

    def post(self, request):
        product_id = request.data.get('product_id', 'P-PLATE01')
        product = get_object_or_404(Product, product_id=product_id, is_active=True)
        img_file = request.FILES.get('image')

        if not img_file:
            return Response({'error': 'Image file is required.'}, status=status.HTTP_400_BAD_REQUEST)

        # Validate
        is_valid, error_msg, metadata = ImageValidationService.validate_file(img_file)

        inspection = Inspection.objects.create(
            engineer=request.user,
            product=product,
            image=img_file,
            image_filename=img_file.name,
            file_size_bytes=metadata.get('file_size_bytes', img_file.size),
            image_width=metadata.get('image_width'),
            image_height=metadata.get('image_height'),
            image_format=metadata.get('image_format', ''),
            status=InspectionStatus.PROCESSING if is_valid else InspectionStatus.FAILED,
            failure_reason=error_msg or '',
        )

        if not is_valid:
            inspection.completed_at = timezone.now()
            inspection.save(update_fields=['status', 'failure_reason', 'completed_at'])
            return Response(InspectionSerializer(inspection).data, status=status.HTTP_400_BAD_REQUEST)

        # Execute model
        try:
            service = get_model_service()
            t0 = time.perf_counter()
            pred = service.classify_image(inspection.image.path)
            t1 = time.perf_counter()

            inspection.predicted_class = pred['predicted_class']
            inspection.confidence = pred['confidence']
            inspection.defect_probability = pred['defect_probability']
            inspection.model_version = pred['model_version']
            inspection.inference_duration_ms = round((t1 - t0) * 1000, 2)
            inspection.status = InspectionStatus.COMPLETED
            inspection.completed_at = timezone.now()
            inspection.save()
            return Response(InspectionSerializer(inspection).data, status=status.HTTP_201_CREATED)

        except Exception as e:
            inspection.status = InspectionStatus.FAILED
            inspection.failure_reason = str(e)
            inspection.completed_at = timezone.now()
            inspection.save()
            return Response(InspectionSerializer(inspection).data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SupervisorReviewAPIView(APIView):
    """
    REST API for supervisor review (Supervisor only).
    Engineers and Administrators receive HTTP 403 Forbidden.
    """
    permission_classes = [IsSupervisorUser]

    def post(self, request, pk):
        inspection = get_object_or_404(Inspection, pk=pk)
        serializer = SupervisorReviewSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        decision = serializer.validated_data['decision']
        notes = serializer.validated_data.get('notes', '')

        if decision == 'CONFIRMED':
            reviewed_class = inspection.predicted_class
        elif decision == 'CORRECTED_NORMAL':
            reviewed_class = InspectionClass.NORMAL
        elif decision == 'CORRECTED_DEFECTIVE':
            reviewed_class = InspectionClass.DEFECTIVE
        else:
            reviewed_class = inspection.predicted_class

        # Never overwrite original AI prediction
        inspection.is_reviewed = True
        inspection.supervisor_decision = decision
        inspection.reviewed_class = reviewed_class
        inspection.supervisor_notes = notes
        inspection.reviewed_by = request.user
        inspection.reviewed_at = timezone.now()
        inspection.save()

        return Response(InspectionSerializer(inspection).data, status=status.HTTP_200_OK)


class InspectionListAPIView(generics.ListAPIView):
    """
    REST API for inspection history:
    - Engineers retrieve their own inspections.
    - Administrators and Supervisors retrieve all inspections across the organization.
    """
    serializer_class = InspectionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = Inspection.objects.select_related('product', 'engineer', 'reviewed_by').order_by('-created_at')
        if getattr(user, 'is_administrator', False) or getattr(user, 'is_supervisor', False):
            return qs
        return qs.filter(engineer=user)


class InspectionDetailAPIView(generics.RetrieveAPIView):
    """
    REST API for inspection detail:
    - Returns full inspection record, prediction, confidence, and review metadata.
    """
    serializer_class = InspectionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        qs = Inspection.objects.select_related('product', 'engineer', 'reviewed_by')
        if getattr(user, 'is_administrator', False) or getattr(user, 'is_supervisor', False):
            return qs
        return qs.filter(engineer=user)

