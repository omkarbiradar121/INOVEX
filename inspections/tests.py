import hashlib
import io
from pathlib import Path
from PIL import Image
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile

from accounts.models import User, UserRole
from products.models import Product
from inspections.models import (
    Inspection,
    InspectionBatch,
    InspectionStatus,
    InspectionClass,
    SupervisorDecision,
    ModelEvaluationRun,
)
from inspections.services import (
    get_model_service,
    QualityInspectionModelService,
    ModelIntegrationError,
    InvalidImageError,
    ImageValidationService,
)


class ModelIntegrityTests(TestCase):
    """
    Tests ensuring original model weights and inference logic remain unmodified.
    """
    EXPECTED_HASHES = {
        'classifier.npz': 'd05a524ac10d6cb864e82da5adb69c0762308ddc05f833fd96eac336c4984ed2',
        'inference.py': '322647cb2e9b5466fe675af56564114532a3c50366ea4fad2961d69a88089ffc',
    }

    def test_model_files_exist(self):
        model_dir = Path(settings.BASE_DIR) / 'Model'
        self.assertTrue((model_dir / 'classifier.npz').exists())
        self.assertTrue((model_dir / 'inference.py').exists())
        self.assertTrue((model_dir / 'model_metadata.json').exists())

    def test_model_files_sha256_unmodified(self):
        model_dir = Path(settings.BASE_DIR) / 'Model'
        for fname, expected_hash in self.EXPECTED_HASHES.items():
            fpath = model_dir / fname
            actual_hash = hashlib.sha256(fpath.read_bytes()).hexdigest()
            self.assertEqual(
                actual_hash.lower(),
                expected_hash.lower(),
                f"Model file {fname} was modified! Hash mismatch."
            )


class ModelInferenceExecutionTests(TestCase):
    """
    Tests checking local model inference accuracy, required output schema, and threshold logic.
    """
    def setUp(self):
        self.service = get_model_service()
        self.samples_dir = Path(settings.BASE_DIR) / 'Samples' / 'images'

    def test_inference_output_schema(self):
        sample_path = self.samples_dir / 'inspection_001.png'
        result = self.service.classify_image(sample_path)

        # 4 required fields
        self.assertIn('predicted_class', result)
        self.assertIn('confidence', result)
        self.assertIn('defect_probability', result)
        self.assertIn('model_version', result)

        self.assertEqual(result['model_version'], 'BIT-PLATE-CV-1.0')
        self.assertIn(result['predicted_class'], ['Normal', 'Defective'])
        self.assertGreaterEqual(result['confidence'], 0.5)
        self.assertLessEqual(result['confidence'], 1.0)
        self.assertGreaterEqual(result['defect_probability'], 0.0)
        self.assertLessEqual(result['defect_probability'], 1.0)

    def test_defective_prediction_on_sample(self):
        # Sample 1 is known defective in labels.csv
        sample_path = self.samples_dir / 'inspection_001.png'
        result = self.service.classify_image(sample_path)
        self.assertEqual(result['predicted_class'], 'Defective')
        self.assertGreaterEqual(result['defect_probability'], 0.5)

    def test_normal_prediction_on_sample(self):
        # Sample 2 is known normal in labels.csv
        sample_path = self.samples_dir / 'inspection_002.jpg'
        result = self.service.classify_image(sample_path)
        self.assertEqual(result['predicted_class'], 'Normal')
        self.assertLess(result['defect_probability'], 0.5)

    def test_local_cpu_execution_no_gpu_required(self):
        # Verify inference runs entirely in pure Python / NumPy / Pillow on CPU
        sample_path = self.samples_dir / 'inspection_003.png'
        result = self.service.classify_image(sample_path)
        self.assertIsNotNone(result)
        self.assertEqual(result['predicted_class'], 'Defective')


class ModelErrorHandlingTests(TestCase):
    """
    Tests verifying robust error handling when encountering missing or corrupt inputs.
    """
    def setUp(self):
        self.service = get_model_service()
        self.validation_dir = Path(settings.BASE_DIR) / 'Validation'

    def test_nonexistent_image_raises_filenotfound(self):
        with self.assertRaises(FileNotFoundError):
            self.service.classify_image("non_existent_file.png")

    def test_corrupt_image_raises_invalid_image_error(self):
        corrupt_path = self.validation_dir / 'corrupt_image.png'
        if corrupt_path.exists():
            with self.assertRaises((InvalidImageError, ModelIntegrationError)):
                self.service.classify_image(corrupt_path)

    def test_not_an_image_raises_invalid_image_error(self):
        not_image_path = self.validation_dir / 'not_an_image.jpg'
        if not_image_path.exists():
            with self.assertRaises((InvalidImageError, ModelIntegrationError)):
                self.service.classify_image(not_image_path)


class SingleInspectionWorkflowTests(TestCase):
    """
    Automated end-to-end tests for Phase 5 (Single Image Inspection Workflow):
    - Role access control (Engineer only)
    - Image pre-inference validation (formats, dimensions, corruption)
    - Local pretrained classifier execution
    - Database persistence of inspection records
    - Result page rendering with required fields (class, confidence, defect_probability, model_version)
    - Personal inspection isolation
    """

    def setUp(self):
        self.engineer = User.objects.create_user(
            username='engineer_tester',
            password='EngPass123!',
            role=UserRole.ENGINEER
        )
        self.other_engineer = User.objects.create_user(
            username='engineer_tester_2',
            password='EngPass123!',
            role=UserRole.ENGINEER
        )
        self.supervisor = User.objects.create_user(
            username='supervisor_tester',
            password='SupPass123!',
            role=UserRole.SUPERVISOR
        )
        self.admin = User.objects.create_user(
            username='admin_tester',
            password='AdminPass123!',
            role=UserRole.ADMIN
        )

        self.product, _ = Product.objects.get_or_create(
            product_id='P-PLATE01',
            defaults={
                'name': 'Demonstration Metal Plate',
                'model_version': 'BIT-PLATE-CV-1.0',
                'classes': 'Normal, Defective',
                'is_active': True,
            }
        )

        self.samples_dir = Path(settings.BASE_DIR) / 'Samples' / 'images'
        self.validation_dir = Path(settings.BASE_DIR) / 'Validation'

    def test_single_inspection_page_accessible_by_engineer(self):
        self.client.login(username='engineer_tester', password='EngPass123!')
        response = self.client.get(reverse('single_inspection'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Single Product Inspection")
        self.assertContains(response, "P-PLATE01")

    def test_single_inspection_page_anonymous_redirects(self):
        response = self.client.get(reverse('single_inspection'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_single_inspection_page_supervisor_forbidden(self):
        self.client.login(username='supervisor_tester', password='SupPass123!')
        response = self.client.get(reverse('single_inspection'))
        self.assertEqual(response.status_code, 403)

    def test_single_inspection_page_admin_forbidden(self):
        self.client.login(username='admin_tester', password='AdminPass123!')
        response = self.client.get(reverse('single_inspection'))
        self.assertEqual(response.status_code, 403)

    def test_single_inspection_upload_defective_sample_success(self):
        self.client.login(username='engineer_tester', password='EngPass123!')
        sample_file = self.samples_dir / 'inspection_001.png'
        self.assertTrue(sample_file.exists())

        with open(sample_file, 'rb') as f:
            uploaded = SimpleUploadedFile(
                name='inspection_001.png',
                content=f.read(),
                content_type='image/png'
            )
            response = self.client.post(
                reverse('single_inspection'),
                {
                    'product': self.product.pk,
                    'image': uploaded,
                },
                follow=True
            )

        self.assertEqual(response.status_code, 200)
        # Verify inspection record in MySQL
        inspection = Inspection.objects.filter(engineer=self.engineer).first()
        self.assertIsNotNone(inspection)
        self.assertEqual(inspection.status, InspectionStatus.COMPLETED)
        self.assertEqual(inspection.predicted_class, 'Defective')
        self.assertEqual(inspection.model_version, 'BIT-PLATE-CV-1.0')
        self.assertGreaterEqual(inspection.confidence, 0.5)
        self.assertGreaterEqual(inspection.defect_probability, 0.5)
        self.assertEqual(inspection.image_filename, 'inspection_001.png')

        # Verify result page content
        self.assertContains(response, "DEFECTIVE")
        self.assertContains(response, "BIT-PLATE-CV-1.0")
        self.assertContains(response, "Defect Probability")
        self.assertContains(response, "Confidence:")

    def test_single_inspection_upload_normal_sample_success(self):
        self.client.login(username='engineer_tester', password='EngPass123!')
        sample_file = self.samples_dir / 'inspection_002.jpg'
        self.assertTrue(sample_file.exists())

        with open(sample_file, 'rb') as f:
            uploaded = SimpleUploadedFile(
                name='inspection_002.jpg',
                content=f.read(),
                content_type='image/jpeg'
            )
            response = self.client.post(
                reverse('single_inspection'),
                {
                    'product': self.product.pk,
                    'image': uploaded,
                },
                follow=True
            )

        self.assertEqual(response.status_code, 200)
        inspection = Inspection.objects.filter(engineer=self.engineer, image_filename='inspection_002.jpg').first()
        self.assertIsNotNone(inspection)
        self.assertEqual(inspection.status, InspectionStatus.COMPLETED)
        self.assertEqual(inspection.predicted_class, 'Normal')
        self.assertLess(inspection.defect_probability, 0.5)
        self.assertContains(response, "NORMAL")

    def test_single_inspection_rejects_corrupted_image(self):
        self.client.login(username='engineer_tester', password='EngPass123!')
        corrupt_file = self.validation_dir / 'corrupt_image.png'
        if corrupt_file.exists():
            with open(corrupt_file, 'rb') as f:
                uploaded = SimpleUploadedFile(
                    name='corrupt_image.png',
                    content=f.read(),
                    content_type='image/png'
                )
                response = self.client.post(
                    reverse('single_inspection'),
                    {
                        'product': self.product.pk,
                        'image': uploaded,
                    }
                )
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Corrupted or invalid image file")
            # Ensure no completed inspection record created
            self.assertEqual(Inspection.objects.filter(engineer=self.engineer).count(), 0)

    def test_single_inspection_rejects_non_image_content(self):
        self.client.login(username='engineer_tester', password='EngPass123!')
        not_image_file = self.validation_dir / 'not_an_image.jpg'
        if not_image_file.exists():
            with open(not_image_file, 'rb') as f:
                uploaded = SimpleUploadedFile(
                    name='not_an_image.jpg',
                    content=f.read(),
                    content_type='image/jpeg'
                )
                response = self.client.post(
                    reverse('single_inspection'),
                    {
                        'product': self.product.pk,
                        'image': uploaded,
                    }
                )
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Corrupted or invalid image file")
            self.assertEqual(Inspection.objects.filter(engineer=self.engineer).count(), 0)

    def test_single_inspection_rejects_undersized_image(self):
        self.client.login(username='engineer_tester', password='EngPass123!')
        too_small_file = self.validation_dir / 'too_small.png'
        if too_small_file.exists():
            with open(too_small_file, 'rb') as f:
                uploaded = SimpleUploadedFile(
                    name='too_small.png',
                    content=f.read(),
                    content_type='image/png'
                )
                response = self.client.post(
                    reverse('single_inspection'),
                    {
                        'product': self.product.pk,
                        'image': uploaded,
                    }
                )
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "below the minimum required resolution")
            self.assertEqual(Inspection.objects.filter(engineer=self.engineer).count(), 0)

    def test_engineer_cannot_view_other_engineer_inspection_result(self):
        # Create inspection as engineer_tester
        inspection = Inspection.objects.create(
            engineer=self.engineer,
            product=self.product,
            image_filename='inspection_test.png',
            status=InspectionStatus.COMPLETED,
            predicted_class='Defective',
            confidence=0.95,
            defect_probability=0.95,
            model_version='BIT-PLATE-CV-1.0'
        )

        # Login as other_engineer and attempt to access
        self.client.login(username='engineer_tester_2', password='EngPass123!')
        response = self.client.get(reverse('inspection_result', args=[inspection.pk]))
        self.assertEqual(response.status_code, 404)


@override_settings(CELERY_TASK_ALWAYS_EAGER=True, CELERY_TASK_EAGER_PROPAGATES=True)
class BatchInspectionWorkflowTests(TestCase):
    """
    Automated end-to-end tests for Phase 6 (Batch Image Inspection Workflow):
    - 1 to 10 images intake limit enforcement
    - Celery task dispatch and independent execution
    - Fault isolation: one invalid image does not stop others in the batch
    - Status transitions: Queued, Processing, Completed, Failed
    - Readable failure reasons stored in MySQL
    - Polling API endpoint returning real-time progress and inspection list
    - Strict Engineer-scoped batch access isolation
    """

    def setUp(self):
        self.engineer = User.objects.create_user(
            username='batch_eng_1',
            password='EngPass123!',
            role=UserRole.ENGINEER
        )
        self.other_engineer = User.objects.create_user(
            username='batch_eng_2',
            password='EngPass123!',
            role=UserRole.ENGINEER
        )
        self.supervisor = User.objects.create_user(
            username='batch_sup_1',
            password='SupPass123!',
            role=UserRole.SUPERVISOR
        )
        self.admin = User.objects.create_user(
            username='batch_admin_1',
            password='AdminPass123!',
            role=UserRole.ADMIN
        )

        self.product, _ = Product.objects.get_or_create(
            product_id='P-PLATE01',
            defaults={
                'name': 'Demonstration Metal Plate',
                'model_version': 'BIT-PLATE-CV-1.0',
                'classes': 'Normal, Defective',
                'is_active': True,
            }
        )

        self.samples_dir = Path(settings.BASE_DIR) / 'Samples' / 'images'
        self.validation_dir = Path(settings.BASE_DIR) / 'Validation'

    def test_batch_upload_page_accessible_by_engineer(self):
        self.client.login(username='batch_eng_1', password='EngPass123!')
        response = self.client.get(reverse('batch_upload'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Batch Product Inspection")
        self.assertContains(response, "Capacity: 1–10 Images")

    def test_batch_upload_anonymous_redirects(self):
        response = self.client.get(reverse('batch_upload'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

    def test_batch_upload_supervisor_forbidden(self):
        self.client.login(username='batch_sup_1', password='SupPass123!')
        response = self.client.get(reverse('batch_upload'))
        self.assertEqual(response.status_code, 403)

    def test_batch_upload_admin_forbidden(self):
        self.client.login(username='batch_admin_1', password='AdminPass123!')
        response = self.client.get(reverse('batch_upload'))
        self.assertEqual(response.status_code, 403)

    def test_batch_upload_rejects_empty_selection(self):
        self.client.login(username='batch_eng_1', password='EngPass123!')
        response = self.client.post(
            reverse('batch_upload'),
            {
                'product': self.product.pk,
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please select at least 1 image")

    def test_batch_upload_rejects_more_than_10_images(self):
        self.client.login(username='batch_eng_1', password='EngPass123!')
        sample_file = self.samples_dir / 'inspection_001.png'
        with open(sample_file, 'rb') as f:
            content = f.read()

        # Create 11 files
        files = [
            SimpleUploadedFile(f'sample_{i}.png', content, content_type='image/png')
            for i in range(11)
        ]

        response = self.client.post(
            reverse('batch_upload'),
            {
                'product': self.product.pk,
                'images': files
            }
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Maximum 10 images allowed per batch")

    def test_mixed_batch_upload_and_fault_isolation(self):
        self.client.login(username='batch_eng_1', password='EngPass123!')

        # 1. Valid Defective image
        with open(self.samples_dir / 'inspection_001.png', 'rb') as f:
            img1 = SimpleUploadedFile('insp_001.png', f.read(), content_type='image/png')

        # 2. Corrupted image in the middle
        with open(self.validation_dir / 'corrupt_image.png', 'rb') as f:
            img2 = SimpleUploadedFile('corrupt.png', f.read(), content_type='image/png')

        # 3. Valid Normal image
        with open(self.samples_dir / 'inspection_002.jpg', 'rb') as f:
            img3 = SimpleUploadedFile('insp_002.jpg', f.read(), content_type='image/jpeg')

        response = self.client.post(
            reverse('batch_upload'),
            {
                'product': self.product.pk,
                'images': [img1, img2, img3]
            },
            follow=True
        )
        self.assertEqual(response.status_code, 200)

        # Batch record exists and was updated
        batch = InspectionBatch.objects.filter(engineer=self.engineer).latest('created_at')
        self.assertEqual(batch.total_images, 3)
        self.assertEqual(batch.completed_count, 2)
        self.assertEqual(batch.failed_count, 1)
        self.assertEqual(batch.progress_percentage, 100)

        # Verify individual inspection statuses
        items = list(batch.inspections.order_by('id'))
        self.assertEqual(len(items), 3)

        # Item 1: Valid defective
        self.assertEqual(items[0].status, InspectionStatus.COMPLETED)
        self.assertEqual(items[0].predicted_class, 'Defective')
        self.assertEqual(items[0].model_version, 'BIT-PLATE-CV-1.0')
        self.assertGreaterEqual(items[0].confidence, 0.5)

        # Item 2: Corrupted file - MUST BE FAILED with readable reason
        self.assertEqual(items[1].status, InspectionStatus.FAILED)
        self.assertIn("Corrupted or invalid image file", items[1].failure_reason)

        # Item 3: Valid normal - MUST SUCCEED despite item 2 failure
        self.assertEqual(items[2].status, InspectionStatus.COMPLETED)
        self.assertEqual(items[2].predicted_class, 'Normal')
        self.assertLess(items[2].defect_probability, 0.5)

        # Check detail page rendering
        detail_resp = self.client.get(reverse('batch_detail', args=[batch.batch_id]))
        self.assertEqual(detail_resp.status_code, 200)
        self.assertContains(detail_resp, "insp_001.png")
        self.assertContains(detail_resp, "corrupt.png")
        self.assertContains(detail_resp, "insp_002.jpg")
        self.assertContains(detail_resp, "Defective")
        self.assertContains(detail_resp, "Normal")
        self.assertContains(detail_resp, "Failed")

    def test_batch_status_api_endpoint(self):
        self.client.login(username='batch_eng_1', password='EngPass123!')
        batch = InspectionBatch.objects.create(
            engineer=self.engineer,
            product=self.product,
            total_images=2,
            status=InspectionStatus.QUEUED
        )
        Inspection.objects.create(
            batch=batch,
            engineer=self.engineer,
            product=self.product,
            image_filename='img1.png',
            status=InspectionStatus.COMPLETED,
            predicted_class='Normal',
            confidence=0.9,
            defect_probability=0.1,
            model_version='BIT-PLATE-CV-1.0'
        )
        Inspection.objects.create(
            batch=batch,
            engineer=self.engineer,
            product=self.product,
            image_filename='img2.png',
            status=InspectionStatus.FAILED,
            failure_reason='Corrupted file',
            model_version='BIT-PLATE-CV-1.0'
        )

        response = self.client.get(reverse('api_batch_status', args=[batch.batch_id]))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['batch_id'], str(batch.batch_id))
        self.assertEqual(data['status'], 'COMPLETED')
        self.assertEqual(data['total_images'], 2)
        self.assertEqual(data['completed_count'], 1)
        self.assertEqual(data['failed_count'], 1)
        self.assertEqual(data['progress_percentage'], 100)

    def test_engineer_cannot_view_other_engineer_batch(self):
        batch = InspectionBatch.objects.create(
            engineer=self.engineer,
            product=self.product,
            total_images=1,
            status=InspectionStatus.QUEUED
        )

        self.client.login(username='batch_eng_2', password='EngPass123!')
        response = self.client.get(reverse('batch_detail', args=[batch.batch_id]))
        self.assertEqual(response.status_code, 404)

        api_response = self.client.get(reverse('api_batch_status', args=[batch.batch_id]))
        self.assertEqual(api_response.status_code, 404)


class ImageValidationServiceUnitTests(TestCase):
    """
    Exhaustive tests for Phase 9 strict image validation rules:
    - JPEG / PNG format verification
    - 5 MiB size limits
    - Dimension boundaries (64x64 to 4096x4096)
    - Corrupt, truncated, empty, and spoofed files
    """

    def test_valid_png_accepted(self):
        buf = io.BytesIO()
        img = Image.new('RGB', (128, 128), color='blue')
        img.save(buf, format='PNG')
        buf.seek(0)
        uploaded = SimpleUploadedFile('test.png', buf.read(), content_type='image/png')
        is_valid, msg, meta = ImageValidationService.validate_file(uploaded)
        self.assertTrue(is_valid)
        self.assertEqual(meta['image_width'], 128)
        self.assertEqual(meta['image_height'], 128)
        self.assertEqual(meta['image_format'], 'PNG')

    def test_valid_jpeg_accepted(self):
        buf = io.BytesIO()
        img = Image.new('RGB', (256, 256), color='gray')
        img.save(buf, format='JPEG')
        buf.seek(0)
        uploaded = SimpleUploadedFile('test.jpg', buf.read(), content_type='image/jpeg')
        is_valid, msg, meta = ImageValidationService.validate_file(uploaded)
        self.assertTrue(is_valid)
        self.assertEqual(meta['image_width'], 256)
        self.assertEqual(meta['image_height'], 256)
        self.assertEqual(meta['image_format'], 'JPEG')

    def test_empty_file_rejected(self):
        uploaded = SimpleUploadedFile('empty.png', b'', content_type='image/png')
        is_valid, msg, meta = ImageValidationService.validate_file(uploaded)
        self.assertFalse(is_valid)
        self.assertIn("empty", msg.lower())

    def test_oversized_file_rejected(self):
        # 5 MiB + 1 byte dummy stream
        oversized = SimpleUploadedFile('huge.png', b'x' * (5 * 1024 * 1024 + 10), content_type='image/png')
        is_valid, msg, meta = ImageValidationService.validate_file(oversized)
        self.assertFalse(is_valid)
        self.assertIn("exceeds the maximum allowed limit", msg)

    def test_undersized_dimensions_rejected(self):
        buf = io.BytesIO()
        img = Image.new('RGB', (32, 32), color='red')
        img.save(buf, format='PNG')
        buf.seek(0)
        uploaded = SimpleUploadedFile('small.png', buf.read(), content_type='image/png')
        is_valid, msg, meta = ImageValidationService.validate_file(uploaded)
        self.assertFalse(is_valid)
        self.assertIn("below the minimum required resolution", msg)

    def test_oversized_dimensions_rejected(self):
        buf = io.BytesIO()
        img = Image.new('RGB', (4097, 64), color='green')
        img.save(buf, format='PNG')
        buf.seek(0)
        uploaded = SimpleUploadedFile('wide.png', buf.read(), content_type='image/png')
        is_valid, msg, meta = ImageValidationService.validate_file(uploaded)
        self.assertFalse(is_valid)
        self.assertIn("exceed the maximum allowed resolution", msg)

    def test_unsupported_format_rejected(self):
        buf = io.BytesIO()
        img = Image.new('RGB', (100, 100), color='white')
        img.save(buf, format='GIF')
        buf.seek(0)
        uploaded = SimpleUploadedFile('test.gif', buf.read(), content_type='image/gif')
        is_valid, msg, meta = ImageValidationService.validate_file(uploaded)
        self.assertFalse(is_valid)
        self.assertIn("Unsupported image format", msg)

    def test_corrupted_image_content_rejected(self):
        corrupt_bytes = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRcorruptpayloadgarbage123456789'
        uploaded = SimpleUploadedFile('corrupt.png', corrupt_bytes, content_type='image/png')
        is_valid, msg, meta = ImageValidationService.validate_file(uploaded)
        self.assertFalse(is_valid)
        self.assertIn("Corrupted or invalid image file", msg)


class SupervisorReviewWorkflowTests(TestCase):
    """
    Automated tests for Phase 8 (Supervisor Quality Oversight & Review):
    - Supervisor permissions and access control
    - Confirmation and Correction of AI predictions
    - Non-destructive audit: original AI prediction & confidence are strictly preserved
    - Strict denial for Engineers attempting review actions (HTTP 403)
    """

    def setUp(self):
        self.supervisor = User.objects.create_user(
            username='supervisor_lead',
            password='SupPass123!',
            role=UserRole.SUPERVISOR
        )
        self.engineer = User.objects.create_user(
            username='engineer_author',
            password='EngPass123!',
            role=UserRole.ENGINEER
        )
        self.admin = User.objects.create_user(
            username='admin_staff',
            password='AdminPass123!',
            role=UserRole.ADMIN
        )

        self.product, _ = Product.objects.get_or_create(
            product_id='P-PLATE01',
            defaults={
                'name': 'Demonstration Metal Plate',
                'model_version': 'BIT-PLATE-CV-1.0',
                'classes': 'Normal, Defective',
                'is_active': True,
            }
        )

        self.inspection = Inspection.objects.create(
            engineer=self.engineer,
            product=self.product,
            image_filename='plate_01.png',
            status=InspectionStatus.COMPLETED,
            predicted_class='Defective',
            confidence=0.9850,
            defect_probability=0.9850,
            model_version='BIT-PLATE-CV-1.0',
            inference_duration_ms=12.5,
        )

    def test_supervisor_dashboard_accessible_by_supervisor(self):
        self.client.login(username='supervisor_lead', password='SupPass123!')
        response = self.client.get(reverse('supervisor_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Supervisor Quality Review Portal")
        self.assertContains(response, "plate_01.png")
        self.assertContains(response, "Defective")

    def test_engineer_cannot_access_supervisor_dashboard(self):
        self.client.login(username='engineer_author', password='EngPass123!')
        response = self.client.get(reverse('supervisor_dashboard'))
        self.assertEqual(response.status_code, 403)

    def test_admin_cannot_access_supervisor_dashboard(self):
        self.client.login(username='admin_staff', password='AdminPass123!')
        response = self.client.get(reverse('supervisor_dashboard'))
        self.assertEqual(response.status_code, 403)

    def test_supervisor_confirm_prediction_preserves_original_ai_fields(self):
        self.client.login(username='supervisor_lead', password='SupPass123!')
        response = self.client.post(
            reverse('supervisor_review', args=[self.inspection.pk]),
            {
                'decision': SupervisorDecision.CONFIRMED,
                'notes': 'Verified defective: visible surface scratch in center.',
            },
            follow=True
        )
        self.assertEqual(response.status_code, 200)

        self.inspection.refresh_from_db()
        # Review audit fields recorded
        self.assertTrue(self.inspection.is_reviewed)
        self.assertEqual(self.inspection.supervisor_decision, SupervisorDecision.CONFIRMED)
        self.assertEqual(self.inspection.reviewed_class, 'Defective')
        self.assertEqual(self.inspection.reviewed_by, self.supervisor)
        self.assertIn("visible surface scratch", self.inspection.supervisor_notes)
        self.assertIsNotNone(self.inspection.reviewed_at)

        # IMMUTABILITY: original AI values unchanged
        self.assertEqual(self.inspection.predicted_class, 'Defective')
        self.assertEqual(self.inspection.confidence, 0.9850)
        self.assertEqual(self.inspection.defect_probability, 0.9850)
        self.assertEqual(self.inspection.model_version, 'BIT-PLATE-CV-1.0')

    def test_supervisor_correct_prediction_preserves_original_ai_fields(self):
        self.client.login(username='supervisor_lead', password='SupPass123!')
        response = self.client.post(
            reverse('supervisor_review', args=[self.inspection.pk]),
            {
                'decision': SupervisorDecision.CORRECTED_NORMAL,
                'notes': 'False positive: shadow caused by side lighting. Plate surface is normal.',
            },
            follow=True
        )
        self.assertEqual(response.status_code, 200)

        self.inspection.refresh_from_db()
        # Review audit records human override
        self.assertTrue(self.inspection.is_reviewed)
        self.assertEqual(self.inspection.supervisor_decision, SupervisorDecision.CORRECTED_NORMAL)
        self.assertEqual(self.inspection.reviewed_class, 'Normal')
        self.assertFalse(self.inspection.is_agreement)

        # IMMUTABILITY: original AI fields must NOT be overwritten!
        self.assertEqual(self.inspection.predicted_class, 'Defective')
        self.assertEqual(self.inspection.confidence, 0.9850)
        self.assertEqual(self.inspection.defect_probability, 0.9850)

    def test_engineer_cannot_access_supervisor_review_view(self):
        self.client.login(username='engineer_author', password='EngPass123!')
        response = self.client.get(reverse('supervisor_review', args=[self.inspection.pk]))
        self.assertEqual(response.status_code, 403)

        post_resp = self.client.post(
            reverse('supervisor_review', args=[self.inspection.pk]),
            {'decision': SupervisorDecision.CONFIRMED}
        )
        self.assertEqual(post_resp.status_code, 403)

    def test_engineer_cannot_review_via_api(self):
        self.client.login(username='engineer_author', password='EngPass123!')
        response = self.client.post(
            reverse('api_supervisor_review', args=[self.inspection.pk]),
            {'decision': 'CONFIRMED'}
        )
        self.assertEqual(response.status_code, 403)

    def test_supervisor_dashboard_filtering(self):
        self.client.login(username='supervisor_lead', password='SupPass123!')

        # Filter by prediction=Defective
        resp = self.client.get(reverse('supervisor_dashboard') + '?prediction=Defective')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "plate_01.png")

        # Filter by prediction=Normal
        resp_norm = self.client.get(reverse('supervisor_dashboard') + '?prediction=Normal')
        self.assertEqual(resp_norm.status_code, 200)
        self.assertNotContains(resp_norm, "plate_01.png")


class ModelEvaluationBenchmarkTests(TestCase):
    """
    Automated tests for Phase 10 (Model Performance Benchmark on 60 Official Samples):
    - Ground truth comparison against Samples/labels.csv
    - Full 60 sample evaluation (30 Normal, 30 Defective)
    - Confusion Matrix, Accuracy, and Defect Recall calculation
    - Zero False Negatives scientific caution notice
    - Role access control (Admin & Supervisor only; Engineer forbidden)
    """

    def setUp(self):
        self.supervisor = User.objects.create_user(
            username='eval_sup',
            password='SupPass123!',
            role=UserRole.SUPERVISOR
        )
        self.admin = User.objects.create_user(
            username='eval_admin',
            password='AdminPass123!',
            role=UserRole.ADMIN
        )
        self.engineer = User.objects.create_user(
            username='eval_eng',
            password='EngPass123!',
            role=UserRole.ENGINEER
        )

    def test_model_evaluation_page_accessible_by_supervisor(self):
        self.client.login(username='eval_sup', password='SupPass123!')
        response = self.client.get(reverse('model_evaluation'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vision Model Performance Benchmark")

    def test_model_evaluation_page_accessible_by_admin(self):
        self.client.login(username='eval_admin', password='AdminPass123!')
        response = self.client.get(reverse('model_evaluation'))
        self.assertEqual(response.status_code, 200)

    def test_model_evaluation_page_forbidden_for_engineer(self):
        self.client.login(username='eval_eng', password='EngPass123!')
        response = self.client.get(reverse('model_evaluation'))
        self.assertEqual(response.status_code, 403)

    def test_60_samples_benchmark_evaluation(self):
        from django.core.management import call_command
        call_command('evaluate_model')

        run = ModelEvaluationRun.objects.latest('executed_at')
        self.assertEqual(run.total_samples, 60)
        self.assertEqual(run.failed_predictions, 0)
        self.assertEqual(run.true_positives, 30)
        self.assertEqual(run.true_negatives, 30)
        self.assertEqual(run.false_positives, 0)
        self.assertEqual(run.false_negatives, 0)
        self.assertEqual(run.accuracy, 1.0)
        self.assertEqual(run.defect_recall, 1.0)
        self.assertEqual(run.defect_precision, 1.0)

        # Confusion matrix schema: rows=Actual, cols=Predicted
        # Order: Normal, Defective -> [[TN, FP], [FN, TP]]
        matrix = run.confusion_matrix_json['matrix']
        self.assertEqual(matrix, [[30, 0], [0, 30]])



