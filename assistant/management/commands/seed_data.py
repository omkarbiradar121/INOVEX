import os
import csv
import secrets
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from django.core.files import File
from assistant.models import CustomUser, Machine, Manual
from assistant.rag_engine import index_manual

class Command(BaseCommand):
    help = "Seeds users, machines, and indexes manuals if present."

    def handle(self, *args, **options):
        self.stdout.write("Seeding default users...")
        
        # 1. Administrator
        admin_pass = os.getenv('SEED_ADMIN_PASSWORD')
        admin_pass_generated = False
        if not admin_pass:
            admin_pass = secrets.token_urlsafe(16)
            admin_pass_generated = True

        admin, created = CustomUser.objects.get_or_create(username='admin')
        admin.role = CustomUser.ROLE_ADMIN
        admin.is_staff = True
        admin.is_superuser = True
        admin.department = 'Operations & Maintenance Management'
        admin.set_password(admin_pass)
        admin.save()
        status_admin = "created" if created else "updated"
        gen_notice_admin = " [Generated temporary password - override with SEED_ADMIN_PASSWORD]" if admin_pass_generated else " [Configured via SEED_ADMIN_PASSWORD]"
        self.stdout.write(self.style.SUCCESS(f"  Admin user {status_admin}: username=admin | password={admin_pass}{gen_notice_admin}"))

        # 2. Engineer
        eng_pass = os.getenv('SEED_ENGINEER_PASSWORD')
        eng_pass_generated = False
        if not eng_pass:
            eng_pass = secrets.token_urlsafe(16)
            eng_pass_generated = True

        eng, created = CustomUser.objects.get_or_create(username='engineer')
        eng.role = CustomUser.ROLE_ENGINEER
        eng.department = 'Mechanical Maintenance'
        eng.set_password(eng_pass)
        eng.save()
        status_eng = "created" if created else "updated"
        gen_notice_eng = " [Generated temporary password - override with SEED_ENGINEER_PASSWORD]" if eng_pass_generated else " [Configured via SEED_ENGINEER_PASSWORD]"
        self.stdout.write(self.style.SUCCESS(f"  Engineer user {status_eng}: username=engineer | password={eng_pass}{gen_notice_eng}"))

        # 3. Supervisor
        sup_pass = os.getenv('SEED_SUPERVISOR_PASSWORD')
        sup_pass_generated = False
        if not sup_pass:
            sup_pass = secrets.token_urlsafe(16)
            sup_pass_generated = True

        sup, created = CustomUser.objects.get_or_create(username='supervisor')
        sup.role = CustomUser.ROLE_SUPERVISOR
        sup.department = 'Plant Supervisory & Quality Control'
        sup.set_password(sup_pass)
        sup.save()
        status_sup = "created" if created else "updated"
        gen_notice_sup = " [Generated temporary password - override with SEED_SUPERVISOR_PASSWORD]" if sup_pass_generated else " [Configured via SEED_SUPERVISOR_PASSWORD]"
        self.stdout.write(self.style.SUCCESS(f"  Supervisor user {status_sup}: username=supervisor | password={sup_pass}{gen_notice_sup}"))

        # 4. Default Machines
        self.stdout.write("Seeding machine registry...")
        hp200, _ = Machine.objects.get_or_create(
            machine_id='M-HP200',
            defaults={
                'name': 'HP-200 Hydraulic Press System',
                'model_number': 'HP-200',
                'description': 'High-tonnage industrial hydraulic press for precision metal stamping and deep drawing.'
            }
        )
        ac90, _ = Machine.objects.get_or_create(
            machine_id='M-AC90',
            defaults={
                'name': 'AC-90 Industrial Rotary Air Compressor',
                'model_number': 'AC-90',
                'description': 'Heavy-duty oil-flooded rotary screw compressor for pneumatic plant utilities.'
            }
        )
        self.stdout.write(self.style.SUCCESS("  Machines registered: M-HP200, M-AC90"))

        # 5. Check Manuals folder and machine_manual_index.csv
        manuals_dir = getattr(settings, 'MANUALS_DIR', settings.BASE_DIR / 'Manuals')
        if not os.path.exists(manuals_dir):
            os.makedirs(manuals_dir, exist_ok=True)
            self.stdout.write(f"  Created Manuals folder at: {manuals_dir}")

        csv_path = manuals_dir / 'machine_manual_index.csv'
        if os.path.exists(csv_path):
            self.stdout.write(f"  Found metadata CSV at {csv_path}. Importing...")
            with open(csv_path, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    m_id = row.get('machine_id', '').strip()
                    doc_id = row.get('document_id', '').strip()
                    title = row.get('title', '').strip()
                    revision = row.get('revision', 'Rev 1.0').strip()
                    filename = row.get('filename', '').strip()
                    if m_id and doc_id and filename:
                        try:
                            mach = Machine.objects.get(machine_id=m_id)
                            pdf_file_path = manuals_dir / filename
                            if os.path.exists(pdf_file_path):
                                man, created_m = Manual.objects.get_or_create(
                                    document_id=doc_id,
                                    defaults={
                                        'machine': mach,
                                        'title': title or filename,
                                        'revision': revision,
                                        'uploaded_by': admin,
                                    }
                                )
                                with open(pdf_file_path, 'rb') as pf:
                                    man.file.save(filename, File(pf), save=True)
                                index_manual(man)
                                self.stdout.write(self.style.SUCCESS(f"    Indexed manual: {doc_id} from {filename}"))
                        except Exception as e:
                            self.stdout.write(self.style.WARNING(f"    Error indexing {filename}: {e}"))
        else:
            self.stdout.write(self.style.NOTICE(f"  Notice: machine_manual_index.csv not found at {csv_path}"))
