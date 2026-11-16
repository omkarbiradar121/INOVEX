from rest_framework import serializers
from incidents.models import QualityIncident, IncidentAction, IncidentReview, ProductSOPMapping
from inspections.models import Inspection


class ProductSOPMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductSOPMapping
        fields = ['id', 'product_id', 'product_name', 'sop_document_id', 'revision', 'pdf_filename', 'required']


class IncidentActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = IncidentAction
        fields = [
            'id', 'action_order', 'action_description',
            'sop_document_id', 'sop_document_name', 'revision',
            'pdf_page_number', 'supporting_passage', 'source_reference'
        ]


class IncidentReviewSerializer(serializers.ModelSerializer):
    supervisor_username = serializers.CharField(source='supervisor.username', read_only=True)

    class Meta:
        model = IncidentReview
        fields = ['id', 'decision', 'supervisor', 'supervisor_username', 'comment', 'reviewed_at']
        read_only_fields = ['id', 'supervisor', 'reviewed_at']


class QualityIncidentListSerializer(serializers.ModelSerializer):
    product_code = serializers.CharField(source='product.product_id', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    inspection_id = serializers.IntegerField(source='inspection.id', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = QualityIncident
        fields = [
            'id', 'incident_id', 'inspection_id', 'product_code', 'product_name',
            'original_prediction', 'original_confidence', 'original_model_version',
            'evidence_status', 'review_status', 'created_by_username',
            'created_at', 'updated_at'
        ]


class QualityIncidentDetailSerializer(serializers.ModelSerializer):
    product_code = serializers.CharField(source='product.product_id', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    inspection_id = serializers.IntegerField(source='inspection.id', read_only=True)
    inspection_image_url = serializers.SerializerMethodField()
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)
    actions = IncidentActionSerializer(many=True, read_only=True)
    reviews = IncidentReviewSerializer(many=True, read_only=True)

    class Meta:
        model = QualityIncident
        fields = [
            'id', 'incident_id', 'inspection_id', 'inspection_image_url',
            'product_code', 'product_name', 'original_prediction',
            'original_confidence', 'original_model_version',
            'incident_summary', 'evidence_status', 'evidence_failure_reason',
            'review_status', 'created_by_username', 'created_at', 'updated_at',
            'actions', 'reviews'
        ]

    def get_inspection_image_url(self, obj):
        if obj.inspection and obj.inspection.image:
            return obj.inspection.image.url
        return None


class IncidentCreateSerializer(serializers.Serializer):
    inspection_id = serializers.IntegerField(required=True)


class ReviewSubmissionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=[
        QualityIncident.REVIEW_APPROVED,
        QualityIncident.REVIEW_NEEDS_INFO
    ], required=True)
    comment = serializers.CharField(required=True, allow_blank=False, min_length=2)
