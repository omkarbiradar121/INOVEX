import os
import fitz
from django.conf import settings
from .mapping_service import get_sops_dir, get_product_sop_mappings


def get_sop_absolute_path(filename):
    return os.path.join(get_sops_dir(), filename)


def read_sop_pages(filename):
    """
    Extracts text page-by-page from an SOP PDF preserving 1-based page numbers.
    """
    pdf_path = get_sop_absolute_path(filename)
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"SOP PDF not found: {filename}")

    pages = []
    doc = fitz.open(pdf_path)
    try:
        for idx, page in enumerate(doc):
            pages.append({
                'page_number': idx + 1,  # Strict 1-based indexing
                'text': page.get_text()
            })
    finally:
        doc.close()
    return pages


def check_product_sop_availability(product_id):
    """
    Validates whether all required SOP documents for a product are present and readable.
    Returns:
        (is_sufficient: bool, mappings: list, failure_reason: str)
    """
    mappings = list(get_product_sop_mappings(product_id))
    if not mappings:
        return False, [], f"No SOP documents mapped for product {product_id} in product_sop_mapping.csv"

    # For P-PLATE01, specifically requires both Q-PLATE-01 and Q-PLATE-02
    if product_id == 'P-PLATE01':
        doc_ids = {m.sop_document_id for m in mappings}
        if not {'Q-PLATE-01', 'Q-PLATE-02'}.issubset(doc_ids):
            return False, mappings, f"Product P-PLATE01 requires both Q-PLATE-01 and Q-PLATE-02. Mapped: {list(doc_ids)}"

    missing_docs = []
    unreadable_docs = []

    for m in mappings:
        if m.required:
            pdf_path = get_sop_absolute_path(m.pdf_filename)
            if not os.path.isfile(pdf_path):
                missing_docs.append(f"{m.sop_document_id} ({m.pdf_filename})")
            else:
                try:
                    pages = read_sop_pages(m.pdf_filename)
                    if not pages or sum(len(p['text'].strip()) for p in pages) == 0:
                        unreadable_docs.append(f"{m.sop_document_id} (empty text layer)")
                except Exception as e:
                    unreadable_docs.append(f"{m.sop_document_id} (read error: {str(e)})")

    if missing_docs:
        return False, mappings, f"Missing required SOP document(s): {', '.join(missing_docs)}"

    if unreadable_docs:
        return False, mappings, f"Unreadable required SOP document(s): {', '.join(unreadable_docs)}"

    return True, mappings, ""
