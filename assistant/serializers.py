from rest_framework import serializers
from .models import CustomUser, Machine, Manual, ManualChunk, QueryLog

class MachineSerializer(serializers.ModelSerializer):
    manual_count = serializers.IntegerField(source='manuals.count', read_only=True)
    chunk_count = serializers.IntegerField(source='chunks.count', read_only=True)

    class Meta:
        model = Machine
        fields = ['id', 'machine_id', 'name', 'model_number', 'description', 'created_at', 'manual_count', 'chunk_count']


class ManualSerializer(serializers.ModelSerializer):
    machine_id_str = serializers.CharField(source='machine.machine_id', read_only=True)
    machine_name = serializers.CharField(source='machine.name', read_only=True)
    uploaded_by_username = serializers.CharField(source='uploaded_by.username', read_only=True)
    chunk_count = serializers.IntegerField(source='chunks.count', read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Manual
        fields = [
            'id', 'document_id', 'title', 'machine', 'machine_id_str', 'machine_name',
            'revision', 'file', 'file_url', 'page_count', 'uploaded_by_username',
            'uploaded_at', 'is_indexed', 'chunk_count'
        ]
        read_only_fields = ['is_indexed', 'page_count', 'uploaded_at']

    def get_file_url(self, obj):
        return obj.file.url if obj.file else ''


class QueryLogSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    machine_id_str = serializers.CharField(source='machine.machine_id', read_only=True)
    machine_name = serializers.CharField(source='machine.name', read_only=True)

    class Meta:
        model = QueryLog
        fields = [
            'id', 'username', 'machine', 'machine_id_str', 'machine_name',
            'question', 'answer', 'status', 'citations', 'timestamp'
        ]
        read_only_fields = ['answer', 'status', 'citations', 'timestamp']


class AskQuestionSerializer(serializers.Serializer):
    machine_id = serializers.CharField(max_length=50)
    question = serializers.CharField()
