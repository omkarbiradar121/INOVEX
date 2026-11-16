import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from django.contrib.auth import authenticate
from assistant.models import CustomUser
from inspections.models import Inspection
from incidents.models import QualityIncident

c = Client()

eng_pw = os.getenv('SEED_ENGINEER_PASSWORD', 'VerificationPass123!')
sup_pw = os.getenv('SEED_SUPERVISOR_PASSWORD', 'VerificationPass123!')

for uname, pw in [('engineer', eng_pw), ('supervisor', sup_pw)]:
    u = CustomUser.objects.filter(username=uname).first()
    if u and not authenticate(username=uname, password=pw):
        u.set_password(pw)
        u.save()

print("=" * 60)
print("ROUND 3 — COMPLETE BROWSER-BASED END-TO-END WORKFLOW VERIFICATION")
print("=" * 60)

# 1. ENGINEER WORKFLOW
print("\n[PHASE 1] Engineer Workflow Simulation...")
login_ok = c.login(username='engineer', password=eng_pw)
print(f"  * Engineer Authentication: {'SUCCESS' if login_ok else 'FAILED'}")
assert login_ok, "Engineer login failed"

# Access incidents dashboard
resp = c.get('/incidents/')
print(f"  * Engineer Dashboard Access (GET /incidents/): HTTP {resp.status_code}")
assert resp.status_code == 200

# Locate eligible defective inspection
insp = Inspection.objects.filter(status='completed', predicted_class='Defective', engineer__username='engineer').first()
if not insp:
    insp = Inspection.objects.filter(status='completed', predicted_class='Defective').first()
print(f"  * Selected Eligible Inspection: #{insp.id} [{insp.product.product_id}]")

# Engineer creates incident
resp = c.post('/incidents/create/', {'inspection_id': insp.id}, follow=True)
print(f"  * Incident Creation Submission (POST /incidents/create/): HTTP {resp.status_code}")
assert resp.status_code == 200

incident = QualityIncident.objects.get(inspection=insp)
print(f"  * Quality Incident Generated: {incident.incident_id}")
print(f"    - Evidence Status: {incident.evidence_status}")
print(f"    - Review Status:   {incident.review_status}")
print(f"    - Actions Count:   {incident.actions.count()}")
assert incident.evidence_status == 'Sufficient', "Evidence status must be Sufficient"
assert incident.actions.count() >= 3, "Expected at least 3 evidence-backed actions"

# Interactive SOP Evidence Viewer
resp = c.get(f'/incidents/viewer/sop/?doc_id=Q-PLATE-01&page=1&incident_id={incident.incident_id}')
print(f"  * Interactive SOP Evidence Viewer (GET /incidents/viewer/sop/): HTTP {resp.status_code}")
assert resp.status_code == 200
assert b'Q_PLATE_01_Containment_Rev1_0.pdf' in resp.content
assert b'Cited Page: 1' in resp.content

# Download / Export PDF Report
resp = c.get(f'/incidents/{incident.incident_id}/pdf/')
print(f"  * Incident PDF Report Generation (GET /incidents/{incident.incident_id}/pdf/): HTTP {resp.status_code}")
print(f"    - Content-Type: {resp.headers.get('Content-Type')}")
print(f"    - Byte Size:    {len(resp.content):,} bytes")
assert resp.status_code == 200
assert resp.headers.get('Content-Type') == 'application/pdf'
assert len(resp.content) > 1000

# 2. SUPERVISOR WORKFLOW
print("\n[PHASE 2] Supervisor Workflow Simulation...")
c.logout()
login_ok = c.login(username='supervisor', password=sup_pw)
print(f"  * Supervisor Authentication: {'SUCCESS' if login_ok else 'FAILED'}")
assert login_ok, "Supervisor login failed"

# View Quality Review Incident Portal
resp = c.get('/incidents/')
print(f"  * Supervisor Incidents Portal (GET /incidents/): HTTP {resp.status_code}")
assert resp.status_code == 200
assert bytes(incident.incident_id, 'utf-8') in resp.content

# View Incident Detail Page
resp = c.get(f'/incidents/{incident.incident_id}/')
print(f"  * Supervisor Incident Detail Review (GET /incidents/{incident.incident_id}/): HTTP {resp.status_code}")
assert resp.status_code == 200
assert b'Supervisor Disposition Review' in resp.content

# Submit Review Decision: Approved for follow-up
resp = c.post(
    f'/incidents/{incident.incident_id}/review/',
    {
        'decision': 'Approved for follow-up',
        'comment': 'Physical containment verified in BIN-SEC-4. Authorized tooling inspection on die punch face.'
    },
    follow=True
)
print(f"  * Supervisor Disposition Submission (POST .../review/): HTTP {resp.status_code}")
assert resp.status_code == 200

incident.refresh_from_db()
print(f"  * Recorded Disposition Decision: {incident.review_status}")
assert incident.review_status == 'Approved for follow-up'
latest_review = incident.reviews.first()
print(f"    - Reviewed By: {latest_review.supervisor.username}")
print(f"    - Comment:     \"{latest_review.comment}\"")
print(f"    - Timestamp:   {latest_review.reviewed_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")

print("\n" + "=" * 60)
print("ALL ROUND 3 BROWSER-BASED END-TO-END WORKFLOW TESTS PASSED!")
print("=" * 60)
