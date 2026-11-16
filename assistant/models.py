from django.db import models
from django.contrib.auth.models import AbstractUser

class CustomUser(AbstractUser):
    ROLE_ADMIN = 'admin'
    ROLE_ENGINEER = 'engineer'
    ROLE_SUPERVISOR = 'supervisor'

    ROLE_CHOICES = (
        (ROLE_ADMIN, 'Administrator'),
        (ROLE_ENGINEER, 'Engineer'),
        (ROLE_SUPERVISOR, 'Supervisor'),
    )

    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_ENGINEER)
    department = models.CharField(max_length=100, blank=True, default='')
    employee_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        default='',
        help_text='Internal staff identification'
    )

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"

    def clean(self):
        super().clean()
        if self.role:
            self.role = self.role.lower()

    def save(self, *args, **kwargs):
        if self.role:
            self.role = self.role.lower()
        super().save(*args, **kwargs)

    @property
    def is_admin_role(self):
        return (self.role or '').lower() == self.ROLE_ADMIN or self.is_superuser

    @property
    def is_engineer_role(self):
        return (self.role or '').lower() == self.ROLE_ENGINEER

    @property
    def is_supervisor_role(self):
        return (self.role or '').lower() == self.ROLE_SUPERVISOR

    # Round 2 compatibility properties
    @property
    def is_administrator(self) -> bool:
        return self.is_admin_role

    @property
    def is_engineer(self) -> bool:
        return self.is_engineer_role

    @property
    def is_supervisor(self) -> bool:
        return self.is_supervisor_role

    @property
    def role_badge_class(self) -> str:
        r = (self.role or '').lower()
        mapping = {
            'admin': 'bg-primary',
            'engineer': 'bg-info text-dark',
            'supervisor': 'bg-warning text-dark',
        }
        return mapping.get(r, 'bg-secondary')


class Machine(models.Model):
    machine_id = models.CharField(max_length=50, unique=True, db_index=True)  # e.g., M-HP200, M-AC90
    name = models.CharField(max_length=200)                                   # e.g., HP-200 Hydraulic Press
    model_number = models.CharField(max_length=100, blank=True, default='')
    description = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['machine_id']

    def __str__(self):
        return f"{self.machine_id} - {self.name}"


class Manual(models.Model):
    document_id = models.CharField(max_length=50, unique=True, db_index=True) # e.g., HP-OPS-01, HP-MNT-01, AC-OM-01
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name='manuals')
    title = models.CharField(max_length=255)
    revision = models.CharField(max_length=50, default='Rev 1.0')
    file = models.FileField(upload_to='manuals/')
    page_count = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(CustomUser, null=True, blank=True, on_delete=models.SET_NULL)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_indexed = models.BooleanField(default=False)

    class Meta:
        ordering = ['document_id']

    def __str__(self):
        return f"{self.document_id} ({self.revision}) - {self.title}"


class ManualChunk(models.Model):
    manual = models.ForeignKey(Manual, on_delete=models.CASCADE, related_name='chunks')
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name='chunks')
    document_id = models.CharField(max_length=50, db_index=True)
    target_machine_id = models.CharField(max_length=50, db_index=True)
    revision = models.CharField(max_length=50)
    page_number = models.PositiveIntegerField()  # 1-based original PDF page number
    chunk_index = models.PositiveIntegerField()
    content = models.TextField()
    embedding = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def machine_id(self):
        return self.target_machine_id or (self.machine.machine_id if self.machine else '')

    class Meta:
        ordering = ['target_machine_id', 'document_id', 'page_number', 'chunk_index']

    def __str__(self):
        return f"{self.document_id} P{self.page_number} Chunk {self.chunk_index}"


class QueryLog(models.Model):
    STATUS_ANSWERED = 'answered'
    STATUS_INSUFFICIENT = 'insufficient-evidence'

    STATUS_CHOICES = (
        (STATUS_ANSWERED, 'Answered'),
        (STATUS_INSUFFICIENT, 'Insufficient Evidence'),
    )

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='queries')
    machine = models.ForeignKey(Machine, on_delete=models.CASCADE, related_name='queries')
    question = models.TextField()
    answer = models.TextField()
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default=STATUS_ANSWERED)
    citations = models.JSONField(default=list, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"[{self.status}] {self.user.username} on {self.machine.machine_id}: {self.question[:40]}"
