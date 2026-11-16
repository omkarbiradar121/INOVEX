from django.core.exceptions import ValidationError, PermissionDenied
from incidents.models import QualityIncident, IncidentReview


def submit_incident_review(incident, user, decision, comment):
    """
    Submits a formal supervisor review for an incident.
    Enforces role permissions, decision validity, and insufficient-evidence barriers.
    """
    # 1. Role verification: Only Supervisors can review
    user_role = getattr(user, 'role', None)
    if user_role != 'supervisor':
        raise PermissionDenied("Only users with the Supervisor role are authorized to submit incident reviews.")

    # 2. Decision validation
    allowed_decisions = [QualityIncident.REVIEW_APPROVED, QualityIncident.REVIEW_NEEDS_INFO]
    if decision not in allowed_decisions:
        raise ValidationError(f"Invalid review decision '{decision}'. Allowed: {allowed_decisions}")

    # 3. Mandatory Comment Check
    if not comment or not comment.strip():
        raise ValidationError("A non-empty review comment is mandatory for all supervisor review decisions.")

    # 4. Strict Insufficient Evidence Barrier
    # An incident with Insufficient evidence cannot be approved for follow-up!
    if incident.evidence_status == QualityIncident.EVIDENCE_INSUFFICIENT:
        if decision == QualityIncident.REVIEW_APPROVED:
            raise ValidationError(
                "An incident with Insufficient evidence cannot be approved for follow-up. "
                "Only 'Needs more information' is permitted until required documentation is verified."
            )

    # 5. Record Review and Update Incident Status
    review = IncidentReview.objects.create(
        incident=incident,
        decision=decision,
        supervisor=user,
        comment=comment.strip()
    )

    incident.review_status = decision
    incident.save(update_fields=['review_status', 'updated_at'])

    return review
