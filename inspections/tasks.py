import time
from celery import shared_task
from django.utils import timezone
from .models import Inspection, InspectionStatus, InspectionBatch
from .services import get_model_service, ImageValidationService


@shared_task(bind=True, max_retries=1)
def process_inspection_task(self, inspection_id: int):
    """
    Celery background worker task for processing an individual inspection image.
    Enforces Phase 9 validation before sending to model.
    One invalid image never halts others in the batch.
    """
    try:
        inspection = Inspection.objects.get(id=inspection_id)
    except Inspection.DoesNotExist:
        return {'status': 'error', 'message': f'Inspection {inspection_id} not found.'}

    inspection.status = InspectionStatus.PROCESSING
    inspection.save(update_fields=['status'])

    # Phase 9: Validate actual image content before inference
    try:
        with open(inspection.image.path, 'rb') as f:
            is_valid, error_msg, metadata = ImageValidationService.validate_file(f)
    except Exception as read_err:
        is_valid = False
        error_msg = f"Failed to access image file on storage: {read_err}"
        metadata = {}

    if not is_valid:
        inspection.status = InspectionStatus.FAILED
        inspection.failure_reason = error_msg or "Validation rejected image."
        inspection.completed_at = timezone.now()
        inspection.save(update_fields=['status', 'failure_reason', 'completed_at'])
        if inspection.batch:
            inspection.batch.refresh_batch_status()
        return {
            'inspection_id': inspection.id,
            'status': 'FAILED',
            'failure_reason': inspection.failure_reason
        }

    # Save validated metadata
    inspection.image_width = metadata.get('image_width')
    inspection.image_height = metadata.get('image_height')
    inspection.image_format = metadata.get('image_format')
    inspection.file_size_bytes = metadata.get('file_size_bytes', inspection.file_size_bytes)

    # Phase 5: Execute local pretrained vision model inference
    try:
        service = get_model_service()
        t0 = time.perf_counter()
        prediction_result = service.classify_image(inspection.image.path)
        t1 = time.perf_counter()

        inspection.predicted_class = prediction_result['predicted_class']
        inspection.confidence = prediction_result['confidence']
        inspection.defect_probability = prediction_result['defect_probability']
        inspection.model_version = prediction_result['model_version']
        inspection.inference_duration_ms = round((t1 - t0) * 1000, 2)
        inspection.status = InspectionStatus.COMPLETED
        inspection.completed_at = timezone.now()
        inspection.save()

    except Exception as inference_err:
        inspection.status = InspectionStatus.FAILED
        inspection.failure_reason = f"Model inference error: {str(inference_err)}"
        inspection.completed_at = timezone.now()
        inspection.save(update_fields=['status', 'failure_reason', 'completed_at'])

    # Update parent batch progress if applicable
    if inspection.batch:
        inspection.batch.refresh_batch_status()

    return {
        'inspection_id': inspection.id,
        'status': inspection.status,
        'predicted_class': inspection.predicted_class,
        'confidence': inspection.confidence,
    }


@shared_task
def process_batch_task(batch_id: int):
    """
    Coordinates execution of all inspections in a batch.
    Dispatches each inspection independently so failure in one never blocks others.
    """
    try:
        batch = InspectionBatch.objects.get(id=batch_id)
    except InspectionBatch.DoesNotExist:
        return {'status': 'error', 'message': f'Batch {batch_id} not found.'}

    batch.status = InspectionStatus.PROCESSING
    batch.save(update_fields=['status', 'updated_at'])

    inspections = batch.inspections.all()
    for inspection in inspections:
        process_inspection_task.delay(inspection.id)

    return {'batch_id': batch.id, 'total_dispatched': inspections.count()}
