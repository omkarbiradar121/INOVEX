from rest_framework import serializers
from .models import Inspection, InspectionBatch, ModelEvaluationRun


class InspectionSerializer(serializers.ModelSerializer):
    engineer_username = serializers.CharField(source='engineer.username', read_only=True)
    product_code = serializers.CharField(source='product.product_id', read_only=True)
    reviewed_by_username = serializers.CharField(source='reviewed_by.username', read_only=True)

    class Meta:
        model = Inspection
        fields = [
            'id',
            'inspection_id',
            'product',
            'product_code',
            'engineer_username',
            'image',
            'image_filename',
            'file_size_bytes',
            'image_width',
            'image_height',
            'image_format',
            'status',
            'failure_reason',
            # Immutable AI prediction
            'predicted_class',
            'confidence',
            'defect_probability',
            'model_version',
            'inference_duration_ms',
            # Supervisor review
            'is_reviewed',
            'supervisor_decision',
            'reviewed_class',
            'supervisor_notes',
            'reviewed_by_username',
            'reviewed_at',
            # Timestamps
            'created_at',
            'completed_at',
        ]
        read_only_fields = [
            'id', 'inspection_id', 'status', 'failure_reason',
            'predicted_class', 'confidence', 'defect_probability', 'model_version',
            'inference_duration_ms', 'is_reviewed', 'supervisor_decision', 'reviewed_class',
            'supervisor_notes', 'reviewed_by_username', 'reviewed_at', 'created_at', 'completed_at'
        ]


class InspectionBatchSerializer(serializers.ModelSerializer):
    inspections = InspectionSerializer(many=True, read_only=True)
    progress_percentage = serializers.IntegerField(read_only=True)
    engineer_username = serializers.CharField(source='engineer.username', read_only=True)
    product_code = serializers.CharField(source='product.product_id', read_only=True)

    class Meta:
        model = InspectionBatch
        fields = [
            'id',
            'batch_id',
            'product_code',
            'engineer_username',
            'total_images',
            'completed_count',
            'failed_count',
            'status',
            'progress_percentage',
            'created_at',
            'updated_at',
            'inspections',
        ]


class SupervisorReviewSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=['CONFIRMED', 'CORRECTED_NORMAL', 'CORRECTED_DEFECTIVE'])
    notes = serializers.CharField(required=False, allow_blank=True)
