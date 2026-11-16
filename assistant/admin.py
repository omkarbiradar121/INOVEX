from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Machine, Manual, ManualChunk, QueryLog

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Role & Department', {'fields': ('role', 'department')}),
    )
    list_display = ['username', 'email', 'role', 'department', 'is_staff']
    list_filter = ['role', 'is_staff', 'is_superuser']

@admin.register(Machine)
class MachineAdmin(admin.ModelAdmin):
    list_display = ['machine_id', 'name', 'model_number', 'created_at']
    search_fields = ['machine_id', 'name']

@admin.register(Manual)
class ManualAdmin(admin.ModelAdmin):
    list_display = ['document_id', 'title', 'machine', 'revision', 'page_count', 'is_indexed', 'uploaded_at']
    list_filter = ['machine', 'revision', 'is_indexed']
    search_fields = ['document_id', 'title']

@admin.register(ManualChunk)
class ManualChunkAdmin(admin.ModelAdmin):
    list_display = ['document_id', 'target_machine_id', 'revision', 'page_number', 'chunk_index']
    list_filter = ['target_machine_id', 'document_id']
    search_fields = ['content']

@admin.register(QueryLog)
class QueryLogAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'user', 'machine', 'status', 'question']
    list_filter = ['status', 'machine', 'user']
    search_fields = ['question', 'answer']
