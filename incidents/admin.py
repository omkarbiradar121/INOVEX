from django.contrib import admin
from .models import QualityIncident, IncidentAction, IncidentReview, ProductSOPMapping


class IncidentActionInline(admin.TabularInline):
    model = IncidentAction
    extra = 0
    readonly_fields = ('action_order', 'action_description', 'sop_document_id', 'revision', 'pdf_page_number', 'source_reference')


class IncidentReviewInline(admin.StackedInline):
    model = IncidentReview
    extra = 0
    readonly_fields = ('supervisor', 'decision', 'comment', 'reviewed_at')


@admin.register(QualityIncident)
class QualityIncidentAdmin(admin.ModelAdmin):
    list_display = ('incident_id', 'product', 'inspection', 'evidence_status', 'review_status', 'created_by', 'created_at')
    list_filter = ('evidence_status', 'review_status', 'product')
    search_fields = ('incident_id', 'inspection__id', 'product__product_id')
    readonly_fields = ('incident_id', 'inspection', 'product', 'original_prediction', 'original_confidence', 'original_model_version', 'created_at', 'updated_at')
    inlines = [IncidentActionInline, IncidentReviewInline]


@admin.register(ProductSOPMapping)
class ProductSOPMappingAdmin(admin.ModelAdmin):
    list_display = ('product_id', 'product_name', 'sop_document_id', 'revision', 'pdf_filename', 'required')
    list_filter = ('required', 'product_id')
    search_fields = ('product_id', 'sop_document_id', 'product_name')
