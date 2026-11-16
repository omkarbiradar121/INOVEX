from rest_framework import serializers
from .models import Product


class ProductSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(source='created_by.username', read_only=True)

    class Meta:
        model = Product
        fields = [
            'id',
            'product_id',
            'name',
            'model_version',
            'classes',
            'description',
            'is_active',
            'created_by_username',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'created_by_username']

    def validate_product_id(self, value):
        pid = value.strip().upper()
        qs = Product.objects.filter(product_id__iexact=pid)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f"Product with ID '{pid}' is already registered.")
        return pid
