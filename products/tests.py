from django.test import TestCase, Client
from django.urls import reverse
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient
from accounts.models import User, UserRole
from products.models import Product


class ProductModelTests(TestCase):
    """
    Unit tests for Product database model and field validations.
    """
    def setUp(self):
        self.admin = User.objects.create_user(
            username='prod_admin',
            password='Password123!',
            role=UserRole.ADMIN
        )

    def test_create_product_success(self):
        product = Product.objects.create(
            product_id='P-PLATE01',
            name='Demonstration Metal Plate',
            model_version='BIT-PLATE-CV-1.0',
            classes='Normal, Defective',
            created_by=self.admin
        )
        self.assertEqual(product.product_id, 'P-PLATE01')
        self.assertEqual(str(product), 'P-PLATE01 - Demonstration Metal Plate')
        self.assertTrue(product.is_active)
        self.assertIsNotNone(product.created_at)

    def test_duplicate_product_id_rejection(self):
        Product.objects.create(
            product_id='P-PLATE01',
            name='Demonstration Metal Plate',
            model_version='BIT-PLATE-CV-1.0',
            created_by=self.admin
        )
        duplicate = Product(
            product_id='p-plate01',  # lowercase duplicate
            name='Another Plate',
            model_version='BIT-PLATE-CV-1.0',
            created_by=self.admin
        )
        with self.assertRaises(ValidationError):
            duplicate.clean()

    def test_product_id_case_normalization(self):
        product = Product.objects.create(
            product_id='  p-plate01  ',
            name='Normalized Plate',
            created_by=self.admin
        )
        self.assertEqual(product.product_id, 'P-PLATE01')


class ProductAdminViewsTests(TestCase):
    """
    Tests for Administrator product management web interface.
    """
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='admin_worker',
            password='Password123!',
            role=UserRole.ADMIN
        )
        self.product = Product.objects.create(
            product_id='P-PLATE01',
            name='Demonstration Metal Plate',
            model_version='BIT-PLATE-CV-1.0',
            classes='Normal, Defective',
            created_by=self.admin
        )

    def test_admin_dashboard_shows_products(self):
        self.client.login(username='admin_worker', password='Password123!')
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'P-PLATE01')
        self.assertContains(response, 'Demonstration Metal Plate')
        self.assertContains(response, 'BIT-PLATE-CV-1.0')

    def test_product_list_view(self):
        self.client.login(username='admin_worker', password='Password123!')
        response = self.client.get(reverse('product_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'P-PLATE01')

    def test_product_detail_view(self):
        self.client.login(username='admin_worker', password='Password123!')
        response = self.client.get(reverse('product_detail', kwargs={'pk': self.product.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Demonstration Metal Plate')
        self.assertContains(response, 'BIT-PLATE-CV-1.0')

    def test_product_registration_success(self):
        self.client.login(username='admin_worker', password='Password123!')
        response = self.client.post(reverse('product_create'), {
            'product_id': 'P-TEST02',
            'name': 'Test Plate 2',
            'model_version': 'BIT-PLATE-CV-1.0',
            'classes': 'Normal, Defective',
            'description': 'Secondary test product',
            'is_active': True,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Product.objects.filter(product_id='P-TEST02').exists())
        self.assertContains(response, "successfully registered")

    def test_product_registration_duplicate_rejected(self):
        self.client.login(username='admin_worker', password='Password123!')
        response = self.client.post(reverse('product_create'), {
            'product_id': 'P-PLATE01',  # duplicate ID
            'name': 'Duplicate Metal Plate',
            'model_version': 'BIT-PLATE-CV-1.0',
            'classes': 'Normal, Defective',
            'is_active': True,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already registered")

    def test_product_edit(self):
        self.client.login(username='admin_worker', password='Password123!')
        response = self.client.post(reverse('product_edit', kwargs={'pk': self.product.pk}), {
            'product_id': 'P-PLATE01',
            'name': 'Updated Demonstration Metal Plate',
            'model_version': 'BIT-PLATE-CV-1.0',
            'classes': 'Normal, Defective',
            'description': 'Updated description',
            'is_active': True,
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name, 'Updated Demonstration Metal Plate')

    def test_product_toggle_status(self):
        self.client.login(username='admin_worker', password='Password123!')
        self.assertTrue(self.product.is_active)
        response = self.client.post(reverse('product_toggle', kwargs={'pk': self.product.pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_active)

    def test_product_delete(self):
        self.client.login(username='admin_worker', password='Password123!')
        pk = self.product.pk
        response = self.client.post(reverse('product_delete', kwargs={'pk': pk}), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(pk=pk).exists())


class ProductRolePermissionEnforcementTests(TestCase):
    """
    Tests strictly verifying that Engineers and Supervisors cannot access
    or execute product management operations.
    """
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(username='adm', password='Password123!', role=UserRole.ADMIN)
        self.engineer = User.objects.create_user(username='eng', password='Password123!', role=UserRole.ENGINEER)
        self.supervisor = User.objects.create_user(username='sup', password='Password123!', role=UserRole.SUPERVISOR)
        self.product = Product.objects.create(
            product_id='P-PLATE01',
            name='Demonstration Metal Plate',
            created_by=self.admin
        )

    def test_unauthenticated_access_denied(self):
        res = self.client.get(reverse('product_create'))
        self.assertEqual(res.status_code, 302)
        self.assertIn(reverse('login'), res.url)

    def test_engineer_cannot_view_products(self):
        self.client.login(username='eng', password='Password123!')
        res = self.client.get(reverse('product_list'))
        self.assertEqual(res.status_code, 403)

    def test_engineer_cannot_register_product(self):
        self.client.login(username='eng', password='Password123!')
        # GET form
        res_get = self.client.get(reverse('product_create'))
        self.assertEqual(res_get.status_code, 403)
        # POST submission
        res_post = self.client.post(reverse('product_create'), {
            'product_id': 'P-HACK01',
            'name': 'Unauthorized Plate',
            'model_version': 'BIT-PLATE-CV-1.0',
        })
        self.assertEqual(res_post.status_code, 403)
        self.assertFalse(Product.objects.filter(product_id='P-HACK01').exists())

    def test_supervisor_cannot_view_products(self):
        self.client.login(username='sup', password='Password123!')
        res = self.client.get(reverse('product_list'))
        self.assertEqual(res.status_code, 403)

    def test_supervisor_cannot_register_product(self):
        self.client.login(username='sup', password='Password123!')
        # GET form
        res_get = self.client.get(reverse('product_create'))
        self.assertEqual(res_get.status_code, 403)
        # POST submission
        res_post = self.client.post(reverse('product_create'), {
            'product_id': 'P-HACK02',
            'name': 'Unauthorized Plate',
            'model_version': 'BIT-PLATE-CV-1.0',
        })
        self.assertEqual(res_post.status_code, 403)
        self.assertFalse(Product.objects.filter(product_id='P-HACK02').exists())


class ProductAPIPermissionTests(TestCase):
    """
    Tests REST API endpoints for product management and role enforcement.
    """
    def setUp(self):
        self.api_client = APIClient()
        self.admin = User.objects.create_user(username='api_adm', password='Password123!', role=UserRole.ADMIN)
        self.engineer = User.objects.create_user(username='api_eng', password='Password123!', role=UserRole.ENGINEER)
        self.supervisor = User.objects.create_user(username='api_sup', password='Password123!', role=UserRole.SUPERVISOR)
        self.product = Product.objects.create(
            product_id='P-PLATE01',
            name='Demonstration Metal Plate',
            created_by=self.admin
        )

    def test_admin_api_list_and_create(self):
        self.api_client.force_authenticate(user=self.admin)
        # List
        res_list = self.api_client.get(reverse('api_product_list_create'))
        self.assertEqual(res_list.status_code, 200)
        self.assertEqual(len(res_list.data), 1)

        # Create
        res_create = self.api_client.post(reverse('api_product_list_create'), {
            'product_id': 'P-API01',
            'name': 'API Plate',
            'model_version': 'BIT-PLATE-CV-1.0',
            'classes': 'Normal, Defective',
        })
        self.assertEqual(res_create.status_code, 201)
        self.assertTrue(Product.objects.filter(product_id='P-API01').exists())

    def test_admin_api_duplicate_rejected(self):
        self.api_client.force_authenticate(user=self.admin)
        res = self.api_client.post(reverse('api_product_list_create'), {
            'product_id': 'P-PLATE01',
            'name': 'Duplicate',
            'model_version': 'BIT-PLATE-CV-1.0',
        })
        self.assertEqual(res.status_code, 400)

    def test_engineer_api_access_forbidden(self):
        self.api_client.force_authenticate(user=self.engineer)
        res_get = self.api_client.get(reverse('api_product_list_create'))
        self.assertEqual(res_get.status_code, 403)

        res_post = self.api_client.post(reverse('api_product_list_create'), {
            'product_id': 'P-FORBIDDEN1',
            'name': 'Forbidden',
            'model_version': 'BIT-PLATE-CV-1.0',
        })
        self.assertEqual(res_post.status_code, 403)

    def test_supervisor_api_access_forbidden(self):
        self.api_client.force_authenticate(user=self.supervisor)
        res_get = self.api_client.get(reverse('api_product_list_create'))
        self.assertEqual(res_get.status_code, 403)

        res_post = self.api_client.post(reverse('api_product_list_create'), {
            'product_id': 'P-FORBIDDEN2',
            'name': 'Forbidden',
            'model_version': 'BIT-PLATE-CV-1.0',
        })
        self.assertEqual(res_post.status_code, 403)
