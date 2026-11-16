import os
import csv
from django.conf import settings
from incidents.models import ProductSOPMapping


def get_mapping_csv_path():
    return os.path.join(settings.BASE_DIR, 'product_sop_mapping.csv')


def get_sops_dir():
    return os.path.join(settings.BASE_DIR, 'SOPs')


def sync_sop_mappings_from_csv():
    """
    Reads product_sop_mapping.csv and synchronizes it into ProductSOPMapping table.
    """
    csv_path = get_mapping_csv_path()
    if not os.path.isfile(csv_path):
        return []

    mappings = []
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            p_id = row.get('product_id', '').strip()
            p_name = row.get('product_name', '').strip()
            doc_id = row.get('sop_document_id', '').strip()
            rev = row.get('revision', '1').strip()
            filename = row.get('pdf_filename', '').strip()
            is_req = row.get('required', 'true').strip().lower() == 'true'

            obj, _ = ProductSOPMapping.objects.update_or_create(
                product_id=p_id,
                sop_document_id=doc_id,
                defaults={
                    'product_name': p_name,
                    'revision': rev,
                    'pdf_filename': filename,
                    'required': is_req,
                }
            )
            mappings.append(obj)
    return mappings


def get_product_sop_mappings(product_id):
    """
    Returns mapped SOP documents strictly for the specified product_id.
    Never returns unmapped documents.
    """
    # Ensure database is synced
    if not ProductSOPMapping.objects.filter(product_id=product_id).exists():
        sync_sop_mappings_from_csv()
    
    return ProductSOPMapping.objects.filter(product_id=product_id)
