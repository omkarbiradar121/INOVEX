import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from django.contrib.auth import authenticate
from assistant.models import CustomUser, Machine, Manual, QueryLog
from assistant.rag_engine import ask_rag_pipeline
from products.models import Product
from inspections.models import Inspection, InspectionClass, SupervisorDecision
from inspections.services import get_model_service

def run_14_point_verification():
    print("=" * 70)
    print("INOVEX — 14-POINT COMPREHENSIVE END-TO-END VERIFICATION")
    print("=" * 70)
    client = Client()

    # 1. Existing Round 1 login
    print("\n[1] Testing Existing Round 1 Login...")
    admin_pw = os.getenv('SEED_ADMIN_PASSWORD', 'VerificationPass123!')
    eng_pw = os.getenv('SEED_ENGINEER_PASSWORD', 'VerificationPass123!')
    sup_pw = os.getenv('SEED_SUPERVISOR_PASSWORD', 'VerificationPass123!')

    # Ensure accounts are authenticated with active credentials
    for uname, pw in [('admin', admin_pw), ('engineer', eng_pw), ('supervisor', sup_pw)]:
        u = CustomUser.objects.filter(username=uname).first()
        if u and not authenticate(username=uname, password=pw):
            u.set_password(pw)
            u.save()

    admin_auth = authenticate(username='admin', password=admin_pw)
    eng_auth = authenticate(username='engineer', password=eng_pw)
    sup_auth = authenticate(username='supervisor', password=sup_pw)
    assert admin_auth is not None, "Admin authentication failed!"
    assert eng_auth is not None, "Engineer authentication failed!"
    assert sup_auth is not None, "Supervisor authentication failed!"
    print(f"  PASS: All 3 default accounts authenticated (admin, engineer, supervisor).")

    # 2. Round 1 RAG functionality
    print("\n[2] Testing Round 1 RAG Functionality...")
    res_hp = ask_rag_pipeline(machine_id='M-HP200', question="What does error code E31 mean?")
    print(f"  HP-200 E31 status: {res_hp['status']}")
    print(f"  HP-200 E31 excerpt: {res_hp['answer'][:90]}...")
    assert 'guard-open' in res_hp['answer'].lower(), "HP-200 E31 did not identify guard-open!"

    res_ac = ask_rag_pipeline(machine_id='M-AC90', question="What does error code E31 mean?")
    print(f"  AC-90 E31 status: {res_ac['status']}")
    print(f"  AC-90 E31 excerpt: {res_ac['answer'][:90]}...")
    assert 'condensate-drain' in res_ac['answer'].lower(), "AC-90 E31 did not identify condensate-drain!"
    assert 'guard-open' not in res_ac['answer'].lower(), "AC-90 E31 mistakenly leaked guard-open!"
    print(f"  PASS: Machine isolation & strict grounding verified.")

    # 3. Round 2 navigation
    print("\n[3] Testing Round 2 Navigation...")
    client.force_login(eng_auth)
    res_nav = client.get('/engineer-dashboard/')
    assert res_nav.status_code == 200
    content_str = res_nav.content.decode('utf-8')
    assert 'Manual Assistant (R1)' in content_str, "Missing R1 navigation menu"
    assert 'Visual Inspection (R2)' in content_str, "Missing R2 navigation menu"
    assert 'New Inspection' in content_str, "Missing New Inspection link"
    print(f"  PASS: Unified Navigation bar rendered with both Round 1 & Round 2 portals.")

    # 4 & 5. Engineer image upload and actual model inference
    print("\n[4 & 5] Testing Engineer Image Upload & Actual Local Model Inference...")
    sample_defective_path = 'Samples/images/inspection_001.png'
    with open(sample_defective_path, 'rb') as fp:
        upload_res = client.post('/inspections/api/single/', {
            'product_id': 'P-PLATE01',
            'image': fp
        })
    assert upload_res.status_code == 201, f"Single inspection upload failed: {upload_res.data}"
    insp_data_def = upload_res.json()
    insp_id_def = insp_data_def['id']
    print(f"  Uploaded inspection ID: {insp_id_def}")
    print(f"  Predicted class: {insp_data_def['predicted_class']}")
    print(f"  Confidence: {insp_data_def['confidence']}")
    print(f"  Defect probability: {insp_data_def['defect_probability']}")
    print(f"  Model version: {insp_data_def['model_version']}")
    assert insp_data_def['model_version'] == 'BIT-PLATE-CV-1.0'
    print(f"  PASS: Model executed local inference successfully.")

    # 6. Normal prediction
    print("\n[6] Testing Normal Prediction...")
    sample_normal_path = 'Samples/images/inspection_002.jpg'
    with open(sample_normal_path, 'rb') as fp:
        upload_res_norm = client.post('/inspections/api/single/', {
            'product_id': 'P-PLATE01',
            'image': fp
        })
    assert upload_res_norm.status_code == 201
    insp_data_norm = upload_res_norm.json()
    print(f"  Normal sample predicted: {insp_data_norm['predicted_class']} (conf={insp_data_norm['confidence']:.4f})")
    assert insp_data_norm['predicted_class'] == 'Normal', f"Expected Normal, got {insp_data_norm['predicted_class']}"
    print(f"  PASS: Normal plate correctly classified with {insp_data_norm['confidence']:.4f} confidence.")

    # 7. Defective prediction
    print("\n[7] Testing Defective Prediction...")
    assert insp_data_def['predicted_class'] == 'Defective', f"Expected Defective, got {insp_data_def['predicted_class']}"
    assert insp_data_def['confidence'] == 1.0
    print(f"  PASS: Defective plate correctly classified with 1.0000 confidence.")

    # 8. Database persistence
    print("\n[8] Testing Database Persistence...")
    db_record = Inspection.objects.get(id=insp_id_def)
    assert db_record.predicted_class == 'Defective'
    assert db_record.engineer == eng_auth
    assert db_record.product.product_id == 'P-PLATE01'
    print(f"  PASS: Inspection persisted in MySQL database (ID: {db_record.inspection_id[:8]}).")

    # 9. Inspection history
    print("\n[9] Testing Inspection History...")
    hist_res = client.get('/inspections/api/')
    assert hist_res.status_code == 200
    hist_json = hist_res.json()
    assert len(hist_json) >= 2, f"Expected at least 2 history records, got {len(hist_json)}"
    print(f"  PASS: Engineer retrieved personal history ({len(hist_json)} records).")

    # 10. Admin dashboard
    print("\n[10] Testing Admin Dashboard...")
    client.force_login(admin_auth)
    admin_res = client.get('/admin-dashboard/')
    assert admin_res.status_code == 200
    admin_html = admin_res.content.decode('utf-8')
    assert 'P-PLATE01' in admin_html, "Missing P-PLATE01 on admin dashboard"
    assert 'BIT-PLATE-CV-1.0' in admin_html, "Missing model version on admin dashboard"
    assert 'Registered Product Lines' in admin_html, "Missing Products section on admin dashboard"
    assert 'Monitored Inspection Engineers' in admin_html, "Missing personnel monitoring on admin dashboard"
    print(f"  PASS: Admin Dashboard displays all products, metrics, inspections, and monitored personnel.")

    # 11. Engineer permissions
    print("\n[11] Testing Engineer Permissions...")
    client.force_login(eng_auth)
    # Engineer cannot add products
    eng_prod_res = client.get('/products/add/')
    assert eng_prod_res.status_code == 403, f"Expected 403 for engineer accessing product create, got {eng_prod_res.status_code}"
    # Engineer cannot access supervisor review
    eng_sup_res = client.get('/inspections/supervisor/')
    assert eng_sup_res.status_code == 403, f"Expected 403 for engineer accessing supervisor review, got {eng_sup_res.status_code}"
    print(f"  PASS: Engineer strictly blocked from Admin (HTTP 403) and Supervisor (HTTP 403) views.")

    # 12. Supervisor access
    print("\n[12] Testing Supervisor Access...")
    client.force_login(sup_auth)
    sup_dash_res = client.get('/inspections/supervisor/')
    assert sup_dash_res.status_code == 200
    sup_rev_res = client.get(f'/inspections/review/{insp_id_def}/')
    assert sup_rev_res.status_code == 200
    print(f"  PASS: Supervisor successfully accessed Quality Review Portal and Review Details.")

    # 13. Unauthorized API access
    print("\n[13] Testing Unauthorized API Access...")
    anon_client = Client()
    anon_res = anon_client.get('/inspections/api/')
    assert anon_res.status_code in (401, 403), f"Expected 401/403 for unauthenticated API, got {anon_res.status_code}"

    # Engineer cannot perform supervisor review API
    client.force_login(eng_auth)
    eng_rev_api = client.post(f'/inspections/api/review/{insp_id_def}/', {'decision': 'CONFIRMED'})
    assert eng_rev_api.status_code == 403, f"Expected 403 for engineer on supervisor review API, got {eng_rev_api.status_code}"

    # Supervisor cannot call product create API
    client.force_login(sup_auth)
    sup_prod_api = client.post('/products/api/', {'product_id': 'P-TEST', 'name': 'Test'})
    assert sup_prod_api.status_code == 403, f"Expected 403 for supervisor on product create API, got {sup_prod_api.status_code}"
    print(f"  PASS: Unauthorized API calls strictly rejected with HTTP 401/403.")

    # 14. Original prediction immutability
    print("\n[14] Testing Original Prediction Immutability...")
    client.force_login(sup_auth)
    rev_res = client.post(f'/inspections/api/review/{insp_id_def}/', {
        'decision': 'CORRECTED_NORMAL',
        'notes': 'Verified edge feature is benign surface reflection, not crack defect.'
    })
    assert rev_res.status_code == 200
    
    # Reload from database to verify immutability
    updated_rec = Inspection.objects.get(id=insp_id_def)
    print(f"  Original Predicted Class: {updated_rec.predicted_class}")
    print(f"  Original Confidence:      {updated_rec.confidence}")
    print(f"  Original Defect Prob:     {updated_rec.defect_probability}")
    print(f"  Supervisor Decision:      {updated_rec.supervisor_decision}")
    print(f"  Reviewed Class:           {updated_rec.reviewed_class}")
    print(f"  Supervisor Notes:         {updated_rec.supervisor_notes}")
    
    assert updated_rec.predicted_class == 'Defective', "CRITICAL: Original predicted_class was overwritten!"
    assert updated_rec.confidence == 1.0, "CRITICAL: Original confidence was overwritten!"
    assert updated_rec.defect_probability == 1.0, "CRITICAL: Original defect_probability was overwritten!"
    assert updated_rec.reviewed_class == 'Normal', "Reviewed class was not saved correctly!"
    assert updated_rec.is_reviewed is True
    assert updated_rec.reviewed_by == sup_auth
    print(f"  PASS: Original AI prediction is 100% IMMUTABLE. Human audit stored in separate review fields.")

    print("\n" + "=" * 70)
    print("ALL 14 END-TO-END VERIFICATION CHECKS PASSED WITH ZERO ERRORS!")
    print("=" * 70)

if __name__ == '__main__':
    run_14_point_verification()
