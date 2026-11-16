import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from products.models import Product


class InspectionStatus(models.TextChoices):
    QUEUED = 'QUEUED', 'Queued'
    PROCESSING = 'PROCESSING', 'Processing'
    COMPLETED = 'COMPLETED', 'Completed'
    FAILED = 'FAILED', 'Failed'


class InspectionClass(models.TextChoices):
    NORMAL = 'Normal', 'Normal'
    DEFECTIVE = 'Defective', 'Defective'


class SupervisorDecision(models.TextChoices):
    CONFIRMED = 'CONFIRMED', 'Confirmed AI Prediction'
    CORRECTED_NORMAL = 'CORRECTED_NORMAL', 'Corrected to Normal'
    CORRECTED_DEFECTIVE = 'CORRECTED_DEFECTIVE', 'Corrected to Defective'


class InspectionBatch(models.Model):
    """
    Groups a batch upload of 1 to 10 product images for Celery background processing.
    """
    batch_id = models.CharField(
        max_length=64,
        unique=True,
        default=uuid.uuid4,
        db_index=True
    )
    engineer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='inspection_batches'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='batches'
    )
    total_images = models.PositiveSmallIntegerField(default=1)
    completed_count = models.PositiveSmallIntegerField(default=0)
    failed_count = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=InspectionStatus.choices,
        default=InspectionStatus.QUEUED,
        db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Inspection Batch'
        verbose_name_plural = 'Inspection Batches'

    def __str__(self):
        return f"Batch {self.batch_id[:8]} ({self.product.product_id}) - {self.status}"

    @property
    def progress_percentage(self) -> int:
        if self.total_images == 0:
            return 100
        processed = self.completed_count + self.failed_count
        return int((processed / self.total_images) * 100)

    def refresh_batch_status(self):
        """
        Recalculates completed/failed counts and overall batch status.
        """
        inspections = self.inspections.all()
        total = inspections.count()
        completed = inspections.filter(status=InspectionStatus.COMPLETED).count()
        failed = inspections.filter(status=InspectionStatus.FAILED).count()
        processing = inspections.filter(status=InspectionStatus.PROCESSING).count()

        self.total_images = total
        self.completed_count = completed
        self.failed_count = failed

        if total > 0 and (completed + failed) == total:
            self.status = InspectionStatus.COMPLETED if failed == 0 else (
                InspectionStatus.FAILED if completed == 0 else InspectionStatus.COMPLETED
            )
        elif processing > 0 or (completed + failed) > 0:
            self.status = InspectionStatus.PROCESSING
        else:
            self.status = InspectionStatus.QUEUED

        self.save(update_fields=['total_images', 'completed_count', 'failed_count', 'status', 'updated_at'])


class Inspection(models.Model):
    """
    Single inspection record.
    Preserves original AI prediction and confidence permanently.
    Supervisor review records are stored separately and never overwrite AI fields.
    """
    inspection_id = models.CharField(
        max_length=64,
        unique=True,
        default=uuid.uuid4,
        db_index=True
    )
    batch = models.ForeignKey(
        InspectionBatch,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='inspections'
    )
    engineer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='inspections'
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='inspections'
    )
    image = models.ImageField(upload_to='inspections/%Y/%m/%d/')
    image_filename = models.CharField(max_length=255)
    file_size_bytes = models.PositiveIntegerField(default=0)
    image_width = models.PositiveIntegerField(null=True, blank=True)
    image_height = models.PositiveIntegerField(null=True, blank=True)
    image_format = models.CharField(max_length=20, blank=True, default='')

    # Processing lifecycle
    status = models.CharField(
        max_length=20,
        choices=InspectionStatus.choices,
        default=InspectionStatus.QUEUED,
        db_index=True
    )
    failure_reason = models.TextField(blank=True, default='')

    # ORIGINAL AI PREDICTION (Immutable)
    predicted_class = models.CharField(
        max_length=20,
        choices=InspectionClass.choices,
        null=True,
        blank=True,
        db_index=True,
        help_text="Immutable original classifier prediction"
    )
    confidence = models.FloatField(
        null=True,
        blank=True,
        help_text="Immutable AI confidence score (0.50 - 1.00)"
    )
    defect_probability = models.FloatField(
        null=True,
        blank=True,
        help_text="Immutable raw sigmoid defect probability (0.00 - 1.00)"
    )
    model_version = models.CharField(
        max_length=50,
        default='BIT-PLATE-CV-1.0',
        help_text="Vision model version used during inference"
    )
    inference_duration_ms = models.FloatField(
        null=True,
        blank=True,
        help_text="Execution time of local inference in milliseconds"
    )

    # SUPERVISOR REVIEW (Stored separately; original AI prediction is NEVER overwritten)
    is_reviewed = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether a Quality Supervisor has reviewed this inspection"
    )
    supervisor_decision = models.CharField(
        max_length=30,
        choices=SupervisorDecision.choices,
        null=True,
        blank=True
    )
    reviewed_class = models.CharField(
        max_length=20,
        choices=InspectionClass.choices,
        null=True,
        blank=True,
        help_text="Final human verified classification"
    )
    supervisor_notes = models.TextField(
        blank=True,
        default='',
        help_text="Audit remarks or defect description added by supervisor"
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_inspections'
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Inspection Record'
        verbose_name_plural = 'Inspection Records'

    def __str__(self):
        return f"INSP-{self.inspection_id[:8]} [{self.product.product_id}] - {self.status}"

    @property
    def final_class(self) -> str:
        """Returns reviewed class if supervisor reviewed, otherwise AI predicted class."""
        if self.is_reviewed and self.reviewed_class:
            return self.reviewed_class
        return self.predicted_class or "Unknown"

    @property
    def is_agreement(self) -> bool:
        """Whether the supervisor agreed with the original AI prediction."""
        if not self.is_reviewed:
            return True
        return self.reviewed_class == self.predicted_class

    @property
    def prediction_badge_class(self) -> str:
        if self.predicted_class == InspectionClass.DEFECTIVE:
            return 'bg-danger text-white'
        elif self.predicted_class == InspectionClass.NORMAL:
            return 'bg-success text-white'
        return 'bg-secondary text-white'

    @property
    def reviewed_badge_class(self) -> str:
        if self.reviewed_class == InspectionClass.DEFECTIVE:
            return 'bg-danger text-white'
        elif self.reviewed_class == InspectionClass.NORMAL:
            return 'bg-success text-white'
        return 'bg-secondary text-white'

    @property
    def status_badge_class(self) -> str:
        mapping = {
            InspectionStatus.QUEUED: 'bg-secondary text-white',
            InspectionStatus.PROCESSING: 'bg-primary text-white',
            InspectionStatus.COMPLETED: 'bg-success text-white',
            InspectionStatus.FAILED: 'bg-danger text-white',
        }
        return mapping.get(self.status, 'bg-secondary text-white')


class ModelEvaluationRun(models.Model):
    """
    Stores metrics calculated on the 60 official sample images (Phase 10).
    """
    model_version = models.CharField(max_length=50, default='BIT-PLATE-CV-1.0')
    total_samples = models.PositiveIntegerField(default=60)
    true_positives = models.PositiveIntegerField(default=0)
    true_negatives = models.PositiveIntegerField(default=0)
    false_positives = models.PositiveIntegerField(default=0)
    false_negatives = models.PositiveIntegerField(default=0)
    failed_predictions = models.PositiveIntegerField(default=0)

    accuracy = models.FloatField(default=0.0)
    defect_recall = models.FloatField(default=0.0)
    defect_precision = models.FloatField(default=0.0)
    f1_score = models.FloatField(default=0.0)

    confusion_matrix_json = models.JSONField(default=dict)
    detailed_results_json = models.JSONField(default=list)

    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    executed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-executed_at']

    @property
    def accuracy_pct(self) -> str:
        return f"{self.accuracy * 100:.2f}%"

    @property
    def defect_recall_pct(self) -> str:
        return f"{self.defect_recall * 100:.2f}%"

    @property
    def defect_precision_pct(self) -> str:
        return f"{self.defect_precision * 100:.2f}%"

    def __str__(self):
        return f"Evaluation Run [{self.model_version}] - Defect Recall: {self.defect_recall:.2%}"
