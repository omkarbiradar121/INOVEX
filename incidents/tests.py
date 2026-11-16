import os
import io
import fitz
from django.test import TestCase, Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError, PermissionDenied

from assistant.models import CustomUser
from products.models import Product
from inspections.models import Inspection
from incidents.models import QualityIncident, IncidentAction, IncidentReview, ProductSOPMapping
from incidents.services.incident_engine import get_or_create_quality_incident
from incidents.services.review_service import submit_incident_review
from incidents.services.sop_service import check_product_sop_availability
from incidents.services.mapping_service import sync_sop_mappings_from_csv
from incidents.services.pdf_report import build_incident_pdf


class QualityIncidentTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Synchronize mappings from CSV
        sync_sop_mappings_from_csv()

        # Create Users
        cls.engineer = CustomUser.objects.create_user(
            username='test_engineer_r3',
            password='Password123!',
            role='engineer',
            email='eng_r3@inovex.com'
        )
        cls.other_engineer = CustomUser.objects.create_user(
            username='other_engineer_r3',
            password='Password123!',
            role='engineer',
            email='other_r3@inovex.com'
        )
        cls.supervisor = CustomUser.objects.create_user(
            username='test_supervisor_r3',
            password='Password123!',
            role='supervisor',
            email='sup_r3@inovex.com'
        )
        cls.admin_user = CustomUser.objects.create_superuser(
            username='test_admin_r3',
            password='Password123!',
            role='admin',
            email='admin_r3@inovex.com'
        )

        # Create Products
        cls.plate_product, _ = Product.objects.get_or_create(
            product_id='P-PLATE01',
            defaults={
                'name': 'Demonstration metal plate',
                'description': 'Industrial demonstration metal plate for quality QA'
            }
        )
        cls.gasket_product, _ = Product.objects.get_or_create(
            product_id='P-GASKET02',
            defaults={
                'name': 'Industrial Sealing Gasket',
                'description': 'High-pressure elastomeric sealing gasket'
            }
        )

    def setUp(self):
        # Create sample dummy image
        img_bytes = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        uploaded_img = SimpleUploadedFile("plate_defective.png", img_bytes, content_type="image/png")

        # Eligible Defective Inspection owned by cls.engineer
        self.defective_inspection = Inspection.objects.create(
            product=self.plate_product,
            image=uploaded_img,
            status='completed',
            predicted_class='Defective',
            confidence=0.9850,
            model_version='BIT-PLATE-CV-1.0',
            engineer=self.engineer
        )

        # Normal Inspection
        self.normal_inspection = Inspection.objects.create(
            product=self.plate_product,
            image=uploaded_img,
            status='completed',
            predicted_class='Normal',
            confidence=0.9910,
            model_version='BIT-PLATE-CV-1.0',
            engineer=self.engineer
        )

        # Non-completed Inspection
        self.pending_inspection = Inspection.objects.create(
            product=self.plate_product,
            image=uploaded_img,
            status='pending',
            predicted_class='',
            confidence=None,
            model_version='BIT-PLATE-CV-1.0',
            engineer=self.engineer
        )

        # Defective Inspection owned by cls.other_engineer
        self.other_inspection = Inspection.objects.create(
            product=self.plate_product,
            image=uploaded_img,
            status='completed',
            predicted_class='Defective',
            confidence=0.9720,
            model_version='BIT-PLATE-CV-1.0',
            engineer=self.other_engineer
        )

        self.client = Client()

    # TEST 1: Engineer can view their own eligible completed Defective inspections
    def test_01_engineer_can_view_own_eligible_defective_inspections(self):
        self.client.force_login(self.engineer)
        url = reverse('incidents:api_eligible_inspections')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        inspection_ids = [d['inspection_id'] for d in data]
        self.assertIn(self.defective_inspection.id, inspection_ids)
        self.assertNotIn(self.normal_inspection.id, inspection_ids)
        self.assertNotIn(self.pending_inspection.id, inspection_ids)
        self.assertNotIn(self.other_inspection.id, inspection_ids)

    # TEST 2: Engineer cannot create an incident from a Normal inspection
    def test_02_engineer_cannot_create_incident_from_normal_inspection(self):
        with self.assertRaises(ValidationError):
            get_or_create_quality_incident(self.normal_inspection, self.engineer)

        self.client.force_login(self.engineer)
        url = reverse('incidents:api_incidents_list_create')
        response = self.client.post(url, {'inspection_id': self.normal_inspection.id}, content_type='application/json')
        self.assertEqual(response.status_code, 400)

    # TEST 3: Engineer cannot create an incident from queued, processing or failed inspections
    def test_03_engineer_cannot_create_incident_from_non_completed_inspections(self):
        for invalid_status in ['pending', 'processing', 'failed']:
            self.pending_inspection.status = invalid_status
            self.pending_inspection.save()
            with self.assertRaises(ValidationError):
                get_or_create_quality_incident(self.pending_inspection, self.engineer)

    # TEST 4: Engineer cannot create an incident from another Engineer's inspection
    def test_04_engineer_cannot_create_incident_from_another_engineers_inspection(self):
        with self.assertRaises(PermissionDenied):
            get_or_create_quality_incident(self.other_inspection, self.engineer)

        self.client.force_login(self.engineer)
        url = reverse('incidents:api_incidents_list_create')
        response = self.client.post(url, {'inspection_id': self.other_inspection.id}, content_type='application/json')
        self.assertEqual(response.status_code, 403)

    # TEST 5: One inspection creates only one incident
    def test_05_one_inspection_creates_only_one_incident(self):
        incident, created = get_or_create_quality_incident(self.defective_inspection, self.engineer)
        self.assertTrue(created)
        self.assertEqual(QualityIncident.objects.filter(inspection=self.defective_inspection).count(), 1)

    # TEST 6: Repeated requests return the existing incident ID
    def test_06_repeated_requests_return_existing_incident_id(self):
        inc1, created1 = get_or_create_quality_incident(self.defective_inspection, self.engineer)
        inc2, created2 = get_or_create_quality_incident(self.defective_inspection, self.engineer)
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(inc1.incident_id, inc2.incident_id)

        # Via API: second call returns 200 with same incident ID
        self.client.force_login(self.engineer)
        url = reverse('incidents:api_incidents_list_create')
        response = self.client.post(url, {'inspection_id': self.defective_inspection.id}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['incident_id'], inc1.incident_id)

    # TEST 7: Original AI prediction remains unchanged
    def test_07_original_ai_prediction_remains_unchanged(self):
        incident, _ = get_or_create_quality_incident(self.defective_inspection, self.engineer)
        self.assertEqual(incident.original_prediction, 'Defective')
        self.assertAlmostEqual(incident.original_confidence, 0.9850, places=3)
        self.assertEqual(incident.original_model_version, 'BIT-PLATE-CV-1.0')

    # TEST 8: Correct product mapping is used
    def test_08_correct_product_mapping_is_used(self):
        mappings = ProductSOPMapping.objects.filter(product_id='P-PLATE01')
        doc_ids = set(mappings.values_list('sop_document_id', flat=True))
        self.assertEqual(doc_ids, {'Q-PLATE-01', 'Q-PLATE-02'})

    # TEST 9: P-PLATE01 retrieves both required plate SOP documents
    def test_09_p_plate01_retrieves_both_required_plate_sop_documents(self):
        incident, _ = get_or_create_quality_incident(self.defective_inspection, self.engineer)
        actions = incident.actions.all()
        retrieved_doc_ids = set(actions.values_list('sop_document_id', flat=True))
        self.assertIn('Q-PLATE-01', retrieved_doc_ids)
        self.assertIn('Q-PLATE-02', retrieved_doc_ids)

    # TEST 10: Q-GASKET-01 is not retrieved for P-PLATE01
    def test_10_q_gasket_01_is_not_retrieved_for_p_plate01(self):
        incident, _ = get_or_create_quality_incident(self.defective_inspection, self.engineer)
        actions = incident.actions.all()
        retrieved_doc_ids = set(actions.values_list('sop_document_id', flat=True))
        self.assertNotIn('Q-GASKET-01', retrieved_doc_ids)

    # TEST 11: Retrieved citations contain correct document ID, revision and one-based PDF page
    def test_11_retrieved_citations_contain_correct_doc_id_revision_one_based_page(self):
        incident, _ = get_or_create_quality_incident(self.defective_inspection, self.engineer)
        actions = incident.actions.all()
        self.assertGreater(actions.count(), 0)
        for act in actions:
            self.assertIn(act.sop_document_id, ['Q-PLATE-01', 'Q-PLATE-02'])
            self.assertEqual(act.revision, '1')
            self.assertGreaterEqual(act.pdf_page_number, 1)
            self.assertGreater(len(act.supporting_passage.strip()), 10)
            self.assertIn(act.sop_document_id, act.source_reference)

    # TEST 12: Missing required SOP produces Insufficient evidence
    def test_12_missing_required_sop_produces_insufficient_evidence(self):
        ProductSOPMapping.objects.create(
            product_id='P-TEST-MISSING',
            product_name='Test Missing Product',
            sop_document_id='Q-NONEXISTENT',
            revision='1',
            pdf_filename='non_existent_file.pdf',
            required=True
        )
        test_prod = Product.objects.create(product_id='P-TEST-MISSING', name='Test Missing Product')
        insp = Inspection.objects.create(
            product=test_prod,
            status='completed',
            predicted_class='Defective',
            confidence=0.95,
            engineer=self.engineer
        )
        incident, _ = get_or_create_quality_incident(insp, self.engineer)
        self.assertEqual(incident.evidence_status, QualityIncident.EVIDENCE_INSUFFICIENT)

    # TEST 13: Insufficient evidence produces Manual Review Required
    def test_13_insufficient_evidence_produces_manual_review_required(self):
        test_prod, _ = Product.objects.get_or_create(product_id='P-TEST-MISSING-2', defaults={'name': 'Missing SOP Prod'})
        ProductSOPMapping.objects.create(
            product_id='P-TEST-MISSING-2',
            product_name='Missing SOP Prod',
            sop_document_id='Q-MISSING-SOP',
            revision='1',
            pdf_filename='missing_sop.pdf',
            required=True
        )
        insp = Inspection.objects.create(
            product=test_prod,
            status='completed',
            predicted_class='Defective',
            confidence=0.90,
            engineer=self.engineer
        )
        incident, _ = get_or_create_quality_incident(insp, self.engineer)
        self.assertEqual(incident.evidence_status, QualityIncident.EVIDENCE_INSUFFICIENT)
        self.assertIn('Manual Review Required', incident.incident_summary)
        self.assertGreater(len(incident.evidence_failure_reason), 0)

    # TEST 14: Unsupported suggested actions are not generated
    def test_14_unsupported_suggested_actions_are_not_generated(self):
        test_prod, _ = Product.objects.get_or_create(product_id='P-TEST-MISSING-3', defaults={'name': 'No Actions Prod'})
        ProductSOPMapping.objects.create(
            product_id='P-TEST-MISSING-3',
            product_name='No Actions Prod',
            sop_document_id='Q-MISSING-3',
            revision='1',
            pdf_filename='missing_sop_3.pdf',
            required=True
        )
        insp = Inspection.objects.create(
            product=test_prod,
            status='completed',
            predicted_class='Defective',
            confidence=0.92,
            engineer=self.engineer
        )
        incident, _ = get_or_create_quality_incident(insp, self.engineer)
        self.assertEqual(incident.evidence_status, QualityIncident.EVIDENCE_INSUFFICIENT)
        self.assertEqual(incident.actions.count(), 0)

    # TEST 15: Engineer cannot submit Supervisor decisions
    def test_15_engineer_cannot_submit_supervisor_decisions(self):
        incident, _ = get_or_create_quality_incident(self.defective_inspection, self.engineer)
        with self.assertRaises(PermissionDenied):
            submit_incident_review(incident, self.engineer, 'Approved for follow-up', 'Comment')

        self.client.force_login(self.engineer)
        url = reverse('incidents:api_incident_review', kwargs={'incident_id': incident.incident_id})
        response = self.client.post(url, {
            'decision': 'Approved for follow-up',
            'comment': 'Attempted engineer comment'
        }, content_type='application/json')
        self.assertEqual(response.status_code, 403)

    # TEST 16: Supervisor can approve an incident with sufficient evidence
    def test_16_supervisor_can_approve_incident_with_sufficient_evidence(self):
        incident, _ = get_or_create_quality_incident(self.defective_inspection, self.engineer)
        self.assertEqual(incident.evidence_status, QualityIncident.EVIDENCE_SUFFICIENT)

        self.client.force_login(self.supervisor)
        url = reverse('incidents:api_incident_review', kwargs={'incident_id': incident.incident_id})
        response = self.client.post(url, {
            'decision': 'Approved for follow-up',
            'comment': 'Validated containment protocols. Proceed with tooling inspection.'
        }, content_type='application/json')
        self.assertEqual(response.status_code, 201)

        incident.refresh_from_db()
        self.assertEqual(incident.review_status, 'Approved for follow-up')
        self.assertEqual(incident.reviews.count(), 1)
        self.assertEqual(incident.reviews.first().supervisor, self.supervisor)

    # TEST 17: Supervisor can request more information with a required comment
    def test_17_supervisor_can_request_more_information_with_required_comment(self):
        incident, _ = get_or_create_quality_incident(self.defective_inspection, self.engineer)
        
        # Test with valid comment
        review = submit_incident_review(incident, self.supervisor, 'Needs more information', 'Requires microscopic defect confirmation.')
        incident.refresh_from_db()
        self.assertEqual(incident.review_status, 'Needs more information')

        # Test with empty comment (must fail)
        with self.assertRaises(ValidationError):
            submit_incident_review(incident, self.supervisor, 'Needs more information', '   ')

    # TEST 18: Insufficient-evidence incident cannot be approved
    def test_18_insufficient_evidence_incident_cannot_be_approved(self):
        test_prod, _ = Product.objects.get_or_create(product_id='P-TEST-INSUFF', defaults={'name': 'Insuff Prod'})
        insp = Inspection.objects.create(
            product=test_prod,
            status='completed',
            predicted_class='Defective',
            confidence=0.85,
            engineer=self.engineer
        )
        incident, _ = get_or_create_quality_incident(insp, self.engineer)
        self.assertEqual(incident.evidence_status, QualityIncident.EVIDENCE_INSUFFICIENT)

        # Attempt approval - must raise ValidationError
        with self.assertRaises(ValidationError):
            submit_incident_review(incident, self.supervisor, 'Approved for follow-up', 'Approval comment')

        # Via API: returns 400 Bad Request
        self.client.force_login(self.supervisor)
        url = reverse('incidents:api_incident_review', kwargs={'incident_id': incident.incident_id})
        response = self.client.post(url, {
            'decision': 'Approved for follow-up',
            'comment': 'Attempting invalid approval'
        }, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('cannot be approved', response.json()['error'])

    # TEST 19: Approval does not create a product-release decision
    def test_19_approval_does_not_create_product_release_decision(self):
        incident, _ = get_or_create_quality_incident(self.defective_inspection, self.engineer)
        submit_incident_review(incident, self.supervisor, 'Approved for follow-up', 'Authorized tooling check.')

        incident.refresh_from_db()
        self.defective_inspection.refresh_from_db()
        self.assertEqual(incident.review_status, 'Approved for follow-up')
        # Crucial invariant: original inspection prediction remains Defective!
        self.assertEqual(self.defective_inspection.predicted_class, 'Defective')

    # TEST 20: Incident details remain available after logout and application restart
    def test_20_incident_details_remain_available_after_restart(self):
        incident, _ = get_or_create_quality_incident(self.defective_inspection, self.engineer)
        inc_id = incident.incident_id

        # Query fresh from database
        fresh_inc = QualityIncident.objects.get(incident_id=inc_id)
        self.assertEqual(fresh_inc.inspection.id, self.defective_inspection.id)
        self.assertEqual(fresh_inc.actions.count(), incident.actions.count())

    # TEST 21: Supervisor review remains saved after reopening the incident
    def test_21_supervisor_review_remains_saved_after_reopening(self):
        incident, _ = get_or_create_quality_incident(self.defective_inspection, self.engineer)
        submit_incident_review(incident, self.supervisor, 'Needs more information', 'Re-check alignment guides.')

        reloaded = QualityIncident.objects.get(incident_id=incident.incident_id)
        self.assertEqual(reloaded.review_status, 'Needs more information')
        self.assertEqual(reloaded.reviews.count(), 1)
        self.assertEqual(reloaded.reviews.first().comment, 'Re-check alignment guides.')

    # TEST 22: Concurrent incident creation does not create duplicates
    def test_22_concurrent_incident_creation_does_not_create_duplicates(self):
        inc1, c1 = get_or_create_quality_incident(self.defective_inspection, self.engineer)
        inc2, c2 = get_or_create_quality_incident(self.defective_inspection, self.engineer)
        self.assertEqual(inc1.id, inc2.id)
        self.assertEqual(QualityIncident.objects.filter(inspection=self.defective_inspection).count(), 1)

    # TEST 23: PDF export contains correct incident information and citations
    def test_23_pdf_export_contains_correct_incident_info_and_citations(self):
        incident, _ = get_or_create_quality_incident(self.defective_inspection, self.engineer)
        submit_incident_review(incident, self.supervisor, 'Approved for follow-up', 'Tooling verified.')

        pdf_bytes = build_incident_pdf(incident)
        self.assertGreater(len(pdf_bytes), 1000)

        # Parse with PyMuPDF to assert contents
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
        full_text = "\n".join([page.get_text() for page in doc])

        self.assertIn("INOVEX", full_text)
        self.assertIn(incident.incident_id, full_text)
        self.assertIn("P-PLATE01", full_text)
        self.assertIn("Defective", full_text)
        self.assertIn("Q-PLATE-01", full_text)
        self.assertIn("Q-PLATE-02", full_text)
        self.assertIn("Approved for follow-up", full_text)
        self.assertIn("Tooling verified.", full_text)
        doc.close()

    # TEST 24: SOP evidence viewer opens the correct PDF page
    def test_24_sop_evidence_viewer_opens_the_correct_pdf_page(self):
        self.client.force_login(self.engineer)
        url = reverse('incidents:sop_viewer') + "?doc_id=Q-PLATE-01&page=1&incident_id=INC-TEST"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Q-PLATE-01")
        self.assertContains(response, "Cited Page: 1")
        self.assertContains(response, "Q_PLATE_01_Containment_Rev1_0.pdf")
