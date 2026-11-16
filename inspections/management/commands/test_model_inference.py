import hashlib
import json
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from inspections.services import get_model_service


class Command(BaseCommand):
    help = 'Demonstrates local ML model inference on sample images and verifies model integrity'

    EXPECTED_HASHES = {
        'classifier.npz': 'd05a524ac10d6cb864e82da5adb69c0762308ddc05f833fd96eac336c4984ed2',
        'inference.py': '322647cb2e9b5466fe675af56564114532a3c50366ea4fad2961d69a88089ffc',
    }

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("=== Phase 4: Model Integration Verification ==="))
        service = get_model_service()

        # 1. Verify model file integrity
        model_dir = Path(settings.BASE_DIR) / 'Model'
        for fname, expected_hash in self.EXPECTED_HASHES.items():
            fpath = model_dir / fname
            if not fpath.exists():
                self.stderr.write(self.style.ERROR(f"Missing model file: {fpath}"))
                return
            h = hashlib.sha256(fpath.read_bytes()).hexdigest()
            if h.lower() != expected_hash.lower():
                self.stderr.write(self.style.ERROR(f"Integrity check failed for {fname}! Hash mismatch."))
                return
            self.stdout.write(self.style.SUCCESS(f"  [INTEGRITY PASS] {fname} matches official SHA256"))

        # 2. Test sample 1 (Defective)
        sample1_path = Path(settings.BASE_DIR) / 'Samples' / 'images' / 'inspection_001.png'
        res1 = service.classify_image(sample1_path)
        self.stdout.write(self.style.SUCCESS(f"\nSample 1: {sample1_path.name}"))
        self.stdout.write(json.dumps(res1, indent=2))
        assert res1['predicted_class'] == 'Defective'

        # 3. Test sample 2 (Normal)
        sample2_path = Path(settings.BASE_DIR) / 'Samples' / 'images' / 'inspection_002.jpg'
        res2 = service.classify_image(sample2_path)
        self.stdout.write(self.style.SUCCESS(f"\nSample 2: {sample2_path.name}"))
        self.stdout.write(json.dumps(res2, indent=2))
        assert res2['predicted_class'] == 'Normal'

        self.stdout.write(self.style.SUCCESS("\nLocal model inference verified successfully on CPU without external APIs or cloud services!"))
