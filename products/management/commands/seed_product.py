from django.core.management.base import BaseCommand
from products.models import Product
from accounts.models import User, UserRole


class Command(BaseCommand):
    help = 'Seeds initial demonstration product P-PLATE01 for Round 2'

    def handle(self, *args, **options):
        admin_user = User.objects.filter(role=UserRole.ADMIN).first()

        product, created = Product.objects.get_or_create(
            product_id='P-PLATE01',
            defaults={
                'name': 'Demonstration Metal Plate',
                'model_version': 'BIT-PLATE-CV-1.0',
                'classes': 'Normal, Defective',
                'description': 'Demonstration metal bipolar plates for automated surface quality defect inspection.',
                'is_active': True,
                'created_by': admin_user,
            }
        )
        action = 'Registered' if created else 'Verified'
        self.stdout.write(self.style.SUCCESS(f"{action} product '{product.product_id}' ({product.name}) - Model: {product.model_version}"))
