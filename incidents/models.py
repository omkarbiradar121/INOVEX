import uuid
from django.db import models
from django.conf import settings


class QualityIncident(models.Model):
    EVIDENCE_SUFFICIENT = 'Sufficient'
    EVIDENCE_INSUFFICIENT = 'Insufficient'
    EVIDENCE_STATUS_CHOICES = [
        (EVIDENCE_SUFFICIENT, 'Sufficient'),
        (EVIDENCE_INSUFFICIENT, 'Insufficient'),
    ]

    REVIEW_PENDING = 'Pending'
    REVIEW_APPROVED = 'Approved for follow-up'
    REVIEW_NEEDS_INFO = 'Needs more information'
    REVIEW_STATUS_CHOICES = [
        (REVIEW_PENDING, 'Pending'),
        (REVIEW_APPROVED, 'Approved for follow-up'),
        (REVIEW_NEEDS_INFO, 'Needs more information'),
    ]

    incident_id = models.CharField(max_length=64, unique=True, db_index=True, editable=False)
    inspection = models.OneToOneField(
        'inspections.Inspection',
        on_delete=models.PROTECT,
        related_name='quality_incident',
        help_text='Enforces strictly one incident per inspection at database level'
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.PROTECT,
        related_name='quality_incidents'
    )
    original_prediction = models.CharField(max_length=50, default='Defective')
    original_confidence = models.FloatField(null=True, blank=True)
    original_model_version = models.CharField(max_length=100, default='BIT-PLATE-CV-1.0')
    
    incident_summary = models.TextField(blank=True, default='')
    evidence_status = models.CharField(
        max_length=20,
        choices=EVIDENCE_STATUS_CHOICES,
        default=EVIDENCE_INSUFFICIENT
    )
    evidence_failure_reason = models.TextField(blank=True, default='')
    review_status = models.CharField(
        max_length=30,
        choices=REVIEW_STATUS_CHOICES,
        default=REVIEW_PENDING
    )
    
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_incidents'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Quality Incident'
        verbose_name_plural = 'Quality Incidents'

    def save(self, *args, **kwargs):
        if not self.incident_id:
            # Generate clean standardized incident ID: INC-YYYYMMDD-<short_hex>
            self.incident_id = f"INC-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.incident_id} ({self.product.product_id}) - {self.evidence_status}"


class IncidentAction(models.Model):
    incident = models.ForeignKey(
        QualityIncident,
        on_delete=models.CASCADE,
        related_name='actions'
    )
    action_order = models.PositiveIntegerField(default=1)
    action_description = models.TextField()
    sop_document_id = models.CharField(max_length=100)
    sop_document_name = models.CharField(max_length=255)
    revision = models.CharField(max_length=20, default='1')
    pdf_page_number = models.PositiveIntegerField(default=1, help_text='1-based PDF page number')
    supporting_passage = models.TextField()
    source_reference = models.CharField(max_length=255)

    class Meta:
        ordering = ['action_order', 'id']
        verbose_name = 'Incident Action'
        verbose_name_plural = 'Incident Actions'

    def __str__(self):
        return f"{self.incident.incident_id} - Action #{self.action_order} ({self.sop_document_id})"


class IncidentReview(models.Model):
    DECISION_APPROVED = 'Approved for follow-up'
    DECISION_NEEDS_INFO = 'Needs more information'
    DECISION_CHOICES = [
        (DECISION_APPROVED, 'Approved for follow-up'),
        (DECISION_NEEDS_INFO, 'Needs more information'),
    ]

    incident = models.ForeignKey(
        QualityIncident,
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    decision = models.CharField(max_length=30, choices=DECISION_CHOICES)
    supervisor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='incident_reviews'
    )
    comment = models.TextField(help_text='Mandatory supervisor comment')
    reviewed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-reviewed_at']
        verbose_name = 'Incident Review'
        verbose_name_plural = 'Incident Reviews'

    def __str__(self):
        return f"{self.incident.incident_id} Review - {self.decision} by {self.supervisor.username}"


class ProductSOPMapping(models.Model):
    product_id = models.CharField(max_length=100, db_index=True)
    product_name = models.CharField(max_length=255)
    sop_document_id = models.CharField(max_length=100)
    revision = models.CharField(max_length=20, default='1')
    pdf_filename = models.CharField(max_length=255)
    required = models.BooleanField(default=True)

    class Meta:
        ordering = ['product_id', 'sop_document_id']
        unique_together = ('product_id', 'sop_document_id')
        verbose_name = 'Product SOP Mapping'
        verbose_name_plural = 'Product SOP Mappings'

    def __str__(self):
        req_str = "Required" if self.required else "Optional"
        return f"{self.product_id} -> {self.sop_document_id} (Rev {self.revision}, {req_str})"
