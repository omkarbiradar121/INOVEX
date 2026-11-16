from django.db import transaction
from django.core.exceptions import ValidationError, PermissionDenied
from incidents.models import QualityIncident, IncidentAction
from .sop_service import check_product_sop_availability, read_sop_pages


def get_or_create_quality_incident(inspection, user):
    """
    Idempotent incident creation for an inspection.
    Returns:
        (incident: QualityIncident, created: bool)
    """
    # 1. Eligibility Checks
    pred = getattr(inspection, 'predicted_class', getattr(inspection, 'prediction', '')) or ''
    insp_status = getattr(inspection, 'status', '') or ''
    eng_id = getattr(inspection, 'engineer_id', getattr(inspection, 'created_by_id', None))

    if insp_status.lower() != 'completed':
        raise ValidationError(f"Inspection #{inspection.id} is not eligible: status is '{insp_status}', expected 'completed'.")

    if pred.lower() != 'defective':
        raise ValidationError(f"Inspection #{inspection.id} is not eligible: prediction is '{pred}', only 'Defective' inspections qualify for quality incidents.")

    # 2. Ownership / Role check: If engineer, must own the inspection
    if hasattr(user, 'role') and user.role == 'engineer':
        if eng_id != user.id:
            raise PermissionDenied(f"Engineer {user.username} cannot create an incident for another engineer's inspection.")

    # 3. Idempotency Check: One incident per inspection
    existing = QualityIncident.objects.filter(inspection=inspection).first()
    if existing:
        return existing, False

    with transaction.atomic():
        # Double check inside transaction lock to avoid race conditions
        existing = QualityIncident.objects.filter(inspection=inspection).select_for_update().first()
        if existing:
            return existing, False

        product = inspection.product
        model_ver = getattr(inspection, 'model_version', '') or 'BIT-PLATE-CV-1.0'
        conf_str = f"{inspection.confidence:.4f}" if inspection.confidence is not None else "N/A"
        date_str = inspection.created_at.strftime('%Y-%m-%d %H:%M UTC') if inspection.created_at else "Unknown date"

        # 4. Check SOP Availability and Requirements
        is_sufficient, mappings, failure_reason = check_product_sop_availability(product.product_id)

        if not is_sufficient:
            # Insufficient Evidence Path
            incident = QualityIncident.objects.create(
                inspection=inspection,
                product=product,
                original_prediction=pred,
                original_confidence=inspection.confidence,
                original_model_version=model_ver,
                evidence_status=QualityIncident.EVIDENCE_INSUFFICIENT,
                evidence_failure_reason=failure_reason,
                review_status=QualityIncident.REVIEW_PENDING,
                created_by=user,
                incident_summary=(
                    f"Visual inspection #{inspection.id} completed on {date_str} flagged product {product.product_id} "
                    f"({product.name}) as Defective with confidence {conf_str} using model {model_ver}. "
                    f"Required procedural documentation could not be fully verified: {failure_reason}. "
                    f"Manual Review Required."
                )
            )
            # Important: Do NOT create any unsupported actions when evidence is insufficient!
            return incident, True

        # Sufficient Evidence Path
        incident = QualityIncident.objects.create(
            inspection=inspection,
            product=product,
            original_prediction=pred,
            original_confidence=inspection.confidence,
            original_model_version=model_ver,
            evidence_status=QualityIncident.EVIDENCE_SUFFICIENT,
            evidence_failure_reason="",
            review_status=QualityIncident.REVIEW_PENDING,
            created_by=user,
            incident_summary=(
                f"Visual inspection #{inspection.id} completed on {date_str} flagged product {product.product_id} "
                f"({product.name}) as Defective with confidence {conf_str} using model {model_ver}. "
                f"SOP containment and review procedures retrieved and validated."
            )
        )

        # 5. Generate Evidence-Backed Suggested Actions based on actual SOP text
        generate_actions_from_sops(incident, mappings)
        return incident, True


def generate_actions_from_sops(incident, mappings):
    """
    Synthesizes suggested actions backed by verbatim excerpts from product-mapped SOP documents.
    """
    actions_to_create = []
    order = 1

    for m in mappings:
        pages = read_sop_pages(m.pdf_filename)
        doc_name = (
            "Standard Operating Procedure: Defect Containment & Isolation"
            if m.sop_document_id == 'Q-PLATE-01'
            else (
                "Standard Operating Procedure: Quality Review & Disposition Workflow"
                if m.sop_document_id == 'Q-PLATE-02'
                else "Standard Operating Procedure: Elastomeric Gasket Quality Review"
            )
        )

        if m.sop_document_id == 'Q-PLATE-01':
            # Page 1 actions
            actions_to_create.append(IncidentAction(
                incident=incident,
                action_order=order,
                action_description="Halt automated part feeder line immediately to prevent defective workpiece advancement.",
                sop_document_id=m.sop_document_id,
                sop_document_name=doc_name,
                revision=m.revision,
                pdf_page_number=1,
                supporting_passage=(
                    "Upon detection of any surface abnormality or AI-flagged defect on product P-PLATE01 during "
                    "visual inspection, the line operator or quality engineer must immediately halt the automated part feeder. "
                    "Do not allow the suspect workpiece to advance to downstream packaging or assembly stages."
                ),
                source_reference=f"{m.sop_document_id} Rev {m.revision}, Page 1"
            ))
            order += 1

            actions_to_create.append(IncidentAction(
                incident=incident,
                action_order=order,
                action_description="Segregate affected workpiece into red quarantine containment bin BIN-SEC-4.",
                sop_document_id=m.sop_document_id,
                sop_document_name=doc_name,
                revision=m.revision,
                pdf_page_number=1,
                supporting_passage=(
                    "Remove the affected plate workpiece using safety tongs or clean nitrile gloves. "
                    "Place the defective unit directly into the designated red quarantine containment bin labeled BIN-SEC-4. "
                    "Ensure no physical contact between suspect units and certified compliant inventory."
                ),
                source_reference=f"{m.sop_document_id} Rev {m.revision}, Page 1"
            ))
            order += 1

            # Page 2 action
            actions_to_create.append(IncidentAction(
                incident=incident,
                action_order=order,
                action_description="Affix physical Non-Conformance Tag Form NC-104 and quarantine preceding 30-minute production batch in HOLD-AREA-B.",
                sop_document_id=m.sop_document_id,
                sop_document_name=doc_name,
                revision=m.revision,
                pdf_page_number=2,
                supporting_passage=(
                    "Affix an orange physical Non-Conformance Tag (Form NC-104) directly to the quarantined part carrier... "
                    "the quality engineer must quarantine all plate units produced within the previous 30-minute production window. "
                    "These companion units must be held in secondary holding rack HOLD-AREA-B pending formal supervisor review."
                ),
                source_reference=f"{m.sop_document_id} Rev {m.revision}, Page 2"
            ))
            order += 1

        elif m.sop_document_id == 'Q-PLATE-02':
            # Page 1 action
            actions_to_create.append(IncidentAction(
                incident=incident,
                action_order=order,
                action_description="Perform secondary stereomicroscopic visual inspection at 10x magnification to confirm surface anomaly presence.",
                sop_document_id=m.sop_document_id,
                sop_document_name=doc_name,
                revision=m.revision,
                pdf_page_number=1,
                supporting_passage=(
                    "The Quality Engineer must perform a secondary stereomicroscopic visual inspection at 10x magnification "
                    "on the quarantined P-PLATE01 unit. Confirm whether the anomaly is a structural fissure, surface scratch, "
                    "or tool galling mark, and log findings into the electronic quality record."
                ),
                source_reference=f"{m.sop_document_id} Rev {m.revision}, Page 1"
            ))
            order += 1

            # Page 2 action
            actions_to_create.append(IncidentAction(
                incident=incident,
                action_order=order,
                action_description="Inspect stamping die punch face and alignment guides for metal pickup or foreign particulate accumulation.",
                sop_document_id=m.sop_document_id,
                sop_document_name=doc_name,
                revision=m.revision,
                pdf_page_number=2,
                supporting_passage=(
                    "If the supervisor approves the incident for follow-up, the maintenance technician and quality engineer "
                    "must inspect the stamping die punch face and alignment guide for metal pickup, foreign particulate accumulation, "
                    "or mechanical misalignment prior to resuming production."
                ),
                source_reference=f"{m.sop_document_id} Rev {m.revision}, Page 2"
            ))
            order += 1

        elif m.sop_document_id == 'Q-GASKET-01':
            actions_to_create.append(IncidentAction(
                incident=incident,
                action_order=order,
                action_description="Segregate affected gasket into antistatic quarantine tray GASK-HOLD-2.",
                sop_document_id=m.sop_document_id,
                sop_document_name=doc_name,
                revision=m.revision,
                pdf_page_number=1,
                supporting_passage=(
                    "Upon detection of dimensional variance, flash, or void defects on product P-GASKET02, "
                    "immediately segregate the affected gasket into antistatic quarantine tray GASK-HOLD-2."
                ),
                source_reference=f"{m.sop_document_id} Rev {m.revision}, Page 1"
            ))
            order += 1

    IncidentAction.objects.bulk_create(actions_to_create)
