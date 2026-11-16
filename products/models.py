from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError


class Product(models.Model):
    """
    Model representing supported manufactured products for visual quality inspection.
    Primary target product: P-PLATE01 (Demonstration Metal Plate).
    """
    product_id = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name="Product ID",
        help_text="Unique product identifier (e.g., P-PLATE01)"
    )
    name = models.CharField(
        max_length=150,
        verbose_name="Product Name",
        help_text="Full product commercial or engineering designation"
    )
    model_version = models.CharField(
        max_length=50,
        default="BIT-PLATE-CV-1.0",
        verbose_name="Vision Model Version",
        help_text="Designated CV classifier version (BIT-PLATE-CV-1.0)"
    )
    classes = models.CharField(
        max_length=100,
        default="Normal, Defective",
        verbose_name="Inspection Classes",
        help_text="Comma-separated target classification classes"
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name="Description / Specifications",
        help_text="Optional manufacturing notes or component specs"
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Active Status",
        help_text="Whether this product line is active for new inspections"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_products",
        verbose_name="Created By"
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Registration Timestamp"
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Last Updated Timestamp"
    )

    class Meta:
        verbose_name = "Product"
        verbose_name_plural = "Products"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.product_id} - {self.name}"

    def clean(self):
        super().clean()
        if self.product_id:
            self.product_id = self.product_id.strip().upper()
            # Verify uniqueness case-insensitively
            qs = Product.objects.filter(product_id__iexact=self.product_id)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError({
                    'product_id': f"A product with ID '{self.product_id}' is already registered."
                })

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
