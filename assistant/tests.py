import os
import io
import pymupdf
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from django.core.files.uploadedfile import SimpleUploadedFile

from .models import CustomUser, Machine, Manual, ManualChunk, QueryLog
from .rag_engine import index_manual, retrieve_relevant_chunks, ask_rag_pipeline


def create_test_pdf(pages_content: list) -> bytes:
    """
    Creates a multi-page PDF in-memory using PyMuPDF.
    """
    doc = pymupdf.open()
    for text in pages_content:
        page = doc.new_page(width=595, height=842)
        rect = pymupdf.Rect(50, 50, 545, 792)
        page.insert_textbox(rect, text, fontsize=11, fontname="helv")
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


class ManufacturingAssistantTestSuite(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Create Users
        cls.admin_user = CustomUser.objects.create_user(
            username='admin_test',
            password='TestPassword123!',
            role=CustomUser.ROLE_ADMIN,
            is_staff=True,
            is_superuser=True
        )

        cls.engineer_user = CustomUser.objects.create_user(
            username='engineer_test',
            password='TestPassword123!',
            role=CustomUser.ROLE_ENGINEER
        )

        cls.supervisor_user = CustomUser.objects.create_user(
            username='supervisor_test',
            password='TestPassword123!',
            role=CustomUser.ROLE_SUPERVISOR
        )

        # Create Machines
        cls.hp200 = Machine.objects.create(
            machine_id='M-HP200',
            name='HP-200 Hydraulic Press System',
            model_number='HP-200',
            description='Industrial hydraulic press for sheet metal.'
        )

        cls.ac90 = Machine.objects.create(
            machine_id='M-AC90',
            name='AC-90 Industrial Air Compressor',
            model_number='AC-90',
            description='Rotary screw industrial compressor.'
        )

        # Load the official three MRIOTHON manuals supplied to the project
        from django.conf import settings
        manuals_dir = os.path.join(settings.BASE_DIR, 'Manuals')
        with open(os.path.join(manuals_dir, 'HP200_Operations_Rev1_0.pdf'), 'rb') as f:
            hp_ops_bytes = f.read()
        with open(os.path.join(manuals_dir, 'HP200_Maintenance_Rev1_0.pdf'), 'rb') as f:
            hp_mnt_bytes = f.read()
        with open(os.path.join(manuals_dir, 'AC90_Operations_Maintenance_Rev1_0.pdf'), 'rb') as f:
            ac_om_bytes = f.read()

        # Create Manual Models
        cls.manual_hp_ops = Manual.objects.create(
            document_id='HP-OPS-01',
            machine=cls.hp200,
            title='HP 200 Operations Manual',
            revision='1.0',
            uploaded_by=cls.admin_user
        )
        cls.manual_hp_ops.file.save('HP200_Operations_Rev1_0.pdf', SimpleUploadedFile('HP200_Operations_Rev1_0.pdf', hp_ops_bytes), save=True)

        cls.manual_hp_mnt = Manual.objects.create(
            document_id='HP-MNT-01',
            machine=cls.hp200,
            title='HP 200 Maintenance Manual',
            revision='1.0',
            uploaded_by=cls.admin_user
        )
        cls.manual_hp_mnt.file.save('HP200_Maintenance_Rev1_0.pdf', SimpleUploadedFile('HP200_Maintenance_Rev1_0.pdf', hp_mnt_bytes), save=True)

        cls.manual_ac_om = Manual.objects.create(
            document_id='AC-OM-01',
            machine=cls.ac90,
            title='AC 90 Operations & Maintenance Manual',
            revision='1.0',
            uploaded_by=cls.admin_user
        )
        cls.manual_ac_om.file.save('AC90_Operations_Maintenance_Rev1_0.pdf', SimpleUploadedFile('AC90_Operations_Maintenance_Rev1_0.pdf', ac_om_bytes), save=True)

        # Index all 3 manuals once
        index_manual(cls.manual_hp_ops)
        index_manual(cls.manual_hp_mnt)
        index_manual(cls.manual_ac_om)

    def setUp(self):
        self.client = APIClient()

    # =========================================================================
    # COMPULSORY TEST 1: Engineer attempts to upload a manual -> Permission denied
    # =========================================================================
    def test_01_engineer_upload_manual_permission_denied(self):
        """
        TEST 1: An Engineer attempts to upload a manual.
        Expected result: Permission denied (HTTP 403 Forbidden).
        """
        self.client.force_authenticate(user=self.engineer_user)
        dummy_pdf = SimpleUploadedFile("forbidden.pdf", b"%PDF-1.4 ...", content_type="application/pdf")
        
        response = self.client.post('/api/manuals/', {
            'machine': self.hp200.id,
            'document_id': 'FORBIDDEN-01',
            'title': 'Unauthorized Manual',
            'revision': 'Rev 1.0',
            'file': dummy_pdf
        }, format='multipart')

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
            "Engineer MUST be denied permission to upload manuals (HTTP 403)."
        )

    # =========================================================================
    # COMPULSORY TEST 2: Engineer selects HP-200 -> Retrieval strictly excludes AC-90
    # =========================================================================
    def test_02_machine_filtered_retrieval_excludes_other_machines(self):
        """
        TEST 2: An Engineer selects HP-200 and asks a question.
        Expected result: Retrieval must exclude all AC-90 passages.
        """
        question = "What does error E17 mean?"
        retrieved_chunks = retrieve_relevant_chunks(machine_id='M-HP200', question=question, top_k=10)
        
        self.assertGreater(len(retrieved_chunks), 0, "Should retrieve relevant HP-200 chunks")
        for chunk in retrieved_chunks:
            self.assertEqual(
                chunk.machine.machine_id,
                'M-HP200',
                f"Retrieved chunk from {chunk.machine.machine_id} violates strict machine isolation!"
            )
            self.assertNotEqual(
                chunk.machine.machine_id,
                'M-AC90',
                "Retrieval for HP-200 MUST NOT contain AC-90 passages."
            )

    # =========================================================================
    # TEST 3: Machine-Specific Error Code Semantics
    # HP-200 E17 = low hydraulic pressure vs AC-90 E17 = high discharge temperature
    # =========================================================================
    def test_03_error_code_e17_semantics(self):
        # Query HP-200 for E17
        res_hp = ask_rag_pipeline(machine_id='M-HP200', question="What does error code E17 mean?")
        self.assertEqual(res_hp['status'], 'answered')
        self.assertIn("low hydraulic pressure", res_hp['answer'].lower())
        self.assertNotIn("discharge temperature", res_hp['answer'].lower())

        # Query AC-90 for E17
        res_ac = ask_rag_pipeline(machine_id='M-AC90', question="What does error code E17 mean?")
        self.assertEqual(res_ac['status'], 'answered')
        self.assertIn("high discharge temperature", res_ac['answer'].lower())
        self.assertNotIn("hydraulic pressure", res_ac['answer'].lower())

    # =========================================================================
    # TEST 4: Machine-Specific Error Code Semantics
    # HP-200 E31 = guard-open indication vs AC-90 E31 = condensate-drain fault
    # =========================================================================
    def test_04_error_code_e31_semantics(self):
        # Query HP-200 for E31
        res_hp = ask_rag_pipeline(machine_id='M-HP200', question="What does error code E31 mean?")
        self.assertEqual(res_hp['status'], 'answered')
        self.assertIn("guard-open", res_hp['answer'].lower())
        self.assertNotIn("condensate-drain", res_hp['answer'].lower())

        # Query AC-90 for E31
        res_ac = ask_rag_pipeline(machine_id='M-AC90', question="What does error code E31 mean?")
        self.assertEqual(res_ac['status'], 'answered')
        self.assertIn("condensate-drain", res_ac['answer'].lower())
        self.assertNotIn("guard-open", res_ac['answer'].lower())

    # =========================================================================
    # TEST 5: Dual HP-200 Manuals Retrieval (Operations + Maintenance)
    # =========================================================================
    def test_05_question_requiring_both_hp200_manuals_retrieves_both_sources(self):
        """
        A question requiring both HP-200 manuals retrieves both sources.
        """
        question = "What is the normal operating pressure range during forming, and what is the planned RF-20 filter replacement interval?"
        res = ask_rag_pipeline(machine_id='M-HP200', question=question)

        self.assertEqual(res['status'], 'answered')
        cited_doc_ids = [c['document_id'] for c in res['citations']]
        
        self.assertIn('HP-OPS-01', cited_doc_ids, "Should cite Operations manual HP-OPS-01")
        self.assertIn('HP-MNT-01', cited_doc_ids, "Should cite Maintenance manual HP-MNT-01")

    # =========================================================================
    # TEST 6: Unsupported Question returns Insufficient Evidence
    # =========================================================================
    def test_06_unsupported_question_returns_insufficient_evidence(self):
        """
        An unsupported question returns:
        'The available manuals do not contain enough information to answer this question.'
        """
        unsupported_question = "What is the recommended laser optical wavelength and galvo mirror calibration frequency?"
        res = ask_rag_pipeline(machine_id='M-HP200', question=unsupported_question)

        self.assertEqual(res['status'], 'insufficient-evidence')
        self.assertIn(
            "the available manuals do not contain enough information to answer this question",
            res['answer'].lower()
        )
        self.assertEqual(len(res['citations']), 0)

    # =========================================================================
    # TEST 7: Citations Contain Correct 1-based PDF Page Numbers
    # =========================================================================
    def test_07_citations_contain_correct_pdf_page_numbers(self):
        """
        Citations contain correct PDF page numbers (1-based positive integers).
        """
        res = ask_rag_pipeline(machine_id='M-HP200', question="What does alarm code E31 mean?")
        self.assertEqual(res['status'], 'answered')
        self.assertGreater(len(res['citations']), 0)

        for cit in res['citations']:
            page = cit.get('page_number')
            self.assertIsInstance(page, int)
            self.assertGreaterEqual(page, 1, "Page number must be a 1-based positive integer")

        # Specifically verify the supporting passage for E31 is on page 2
        e31_citations = [c for c in res['citations'] if 'guard-open' in c['passage_text'].lower() or 'e31' in c['passage_text'].lower()]
        self.assertGreater(len(e31_citations), 0, "Must have citation for E31")
        for cit in e31_citations:
            self.assertEqual(cit['page_number'], 2, "E31 alarm citation must point to original PDF page 2")
            self.assertEqual(cit['document_id'], "HP-OPS-01")

    # =========================================================================
    # TEST 8: Full API Ask Endpoint with Persistence
    # =========================================================================
    def test_08_api_ask_endpoint_persists_query(self):
        self.client.force_authenticate(user=self.engineer_user)
        response = self.client.post('/api/ask/', {
            'machine_id': 'M-HP200',
            'question': 'What does error code E17 mean?'
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data['status'], 'answered')
        self.assertIn('query_id', data)

        # Verify DB persistence
        log = QueryLog.objects.get(id=data['query_id'])
        self.assertEqual(log.user, self.engineer_user)
        self.assertEqual(log.machine.machine_id, 'M-HP200')
        self.assertEqual(log.status, 'answered')

    # =========================================================================
    # TEST 9: PDF Maintenance Report Download & Layout Verification
    # =========================================================================
    def test_09_download_pdf_report_formatting_and_layout(self):
        """
        Verify that downloading the PDF maintenance report returns a well-formatted,
        publication-grade multi-page PDF document with correct metadata, citations,
        parameters, and running headers/footers.
        """
        # Create an answered query log
        query_log = QueryLog.objects.create(
            user=self.engineer_user,
            machine=self.hp200,
            question="What is the standard procedure for alarm code E17 and what is the required hydraulic fluid?",
            answer=(
                "Alarm code E17 indicates low hydraulic pressure where pressure has dropped below the 110-140 bar threshold. "
                "The operator must immediately switch the cycle to HOLD, inspect the oil reservoir level via the sight-glass, "
                "check for visible hydraulic leaks, and inspect the RF-20 return filter indicator. "
                "The specified operating fluid is H46 Hydraulic Oil."
            ),
            status=QueryLog.STATUS_ANSWERED,
            citations=[
                {
                    "document_id": "HP-OPS-01",
                    "document_name": "HP 200 Operations Manual",
                    "revision": "1.0",
                    "page_number": 2,
                    "passage_text": "E17 | Low hydraulic pressure: Record pressure and cycle stage; place on HOLD and request the checks in HP-MNT-01 page 3."
                },
                {
                    "document_id": "HP-MNT-01",
                    "document_name": "HP 200 Maintenance Manual",
                    "revision": "1.0",
                    "page_number": 3,
                    "passage_text": "Low hydraulic pressure or E17: Collect these observations in order: (1) reservoir level relative to MIN and MAX; (2) visible external leakage; (3) RF-20 restriction-indicator state."
                }
            ]
        )

        # Authenticate as Engineer (owner)
        self.client.force_authenticate(user=self.engineer_user)
        response = self.client.get(f'/api/queries/{query_log.id}/download-pdf/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertIn('attachment;', response['Content-Disposition'])
        self.assertIn(f'Maintenance_Report_M-HP200_Q{query_log.id}.pdf', response['Content-Disposition'])

        pdf_bytes = response.content
        self.assertGreater(len(pdf_bytes), 2000, "PDF must not be empty")

        # Open and inspect the generated PDF structure using PyMuPDF
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        self.assertGreaterEqual(doc.page_count, 1, "PDF must have at least one page")

        full_text = ""
        for page_idx in range(doc.page_count):
            page = doc[page_idx]
            page_text = page.get_text()
            full_text += page_text

            # Verify running footer on all pages
            self.assertIn("Manufacturing Manual Assistant", page_text)
            self.assertIn(f"Page {page_idx + 1} of {doc.page_count}", page_text)

        # Verify structured content sections
        full_text_upper = full_text.upper().replace("’", "'").replace("–", "-").replace("—", "-")
        self.assertIn("MANUFACTURING MANUAL ASSISTANT", full_text_upper)
        self.assertIn("ANSWER REPORT", full_text_upper)
        self.assertIn("DATE AND TIME:", full_text_upper)
        self.assertIn("SELECTED MACHINE:", full_text_upper)
        self.assertIn("M-HP200", full_text_upper)
        self.assertIn("ENGINEER'S QUESTION", full_text_upper)
        self.assertIn("GENERATED ANSWER", full_text_upper)
        self.assertIn("SUPPORTING MANUAL REFERENCES", full_text_upper)
        self.assertIn("HP-MNT-01", full_text_upper)
        self.assertIn("PAGE 3", full_text_upper)
        self.assertIn("HP-OPS-01", full_text_upper)
        self.assertIn("PAGE 2", full_text_upper)
        self.assertIn("ANSWER STATUS", full_text_upper)
        self.assertIn("STATUS: ANSWERED", full_text_upper)

        doc.close()

    # =========================================================================
    # TEST 10: PDF Permissions & Insufficient Evidence Handling
    # =========================================================================
    def test_10_pdf_report_permissions_and_insufficient_evidence(self):
        """
        Verify role-based access control for PDF reports:
        - Engineers cannot download other engineers' reports (403 Forbidden).
        - Supervisors and Admins can download any report (200 OK).
        - Insufficient evidence reports format properly with warning badges.
        """
        # Create a second engineer
        other_engineer = CustomUser.objects.create_user(
            username='other_engineer',
            password='Password123!',
            role=CustomUser.ROLE_ENGINEER
        )

        unanswered_log = QueryLog.objects.create(
            user=self.engineer_user,
            machine=self.ac90,
            question="What is the galvo laser wavelength?",
            answer="The available manuals do not contain enough information to answer this question.",
            status=QueryLog.STATUS_INSUFFICIENT,
            citations=[]
        )

        # 1. Other engineer attempts download -> 403 Forbidden
        self.client.force_authenticate(user=other_engineer)
        res_forbidden = self.client.get(f'/api/queries/{unanswered_log.id}/download-pdf/')
        self.assertEqual(res_forbidden.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Supervisor downloads -> 200 OK
        self.client.force_authenticate(user=self.supervisor_user)
        res_sup = self.client.get(f'/api/queries/{unanswered_log.id}/download-pdf/')
        self.assertEqual(res_sup.status_code, status.HTTP_200_OK)

        # 3. Admin downloads -> 200 OK
        self.client.force_authenticate(user=self.admin_user)
        res_admin = self.client.get(f'/api/queries/{unanswered_log.id}/download-pdf/')
        self.assertEqual(res_admin.status_code, status.HTTP_200_OK)

        # Verify insufficient evidence styling and content
        doc = pymupdf.open(stream=res_admin.content, filetype="pdf")
        full_text = "".join(doc[i].get_text() for i in range(doc.page_count))
        full_text_upper = full_text.upper()
        self.assertIn("MANUFACTURING MANUAL ASSISTANT", full_text_upper)
        self.assertIn("ANSWER REPORT", full_text_upper)
        self.assertIn("STATUS: INSUFFICIENT EVIDENCE", full_text_upper)
        self.assertIn("THE AVAILABLE MANUALS DO NOT CONTAIN ENOUGH INFORMATION", full_text_upper)
        self.assertIn("M-AC90", full_text_upper)
        doc.close()
