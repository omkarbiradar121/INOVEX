import csv
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings

from inspections.models import ModelEvaluationRun
from inspections.services import get_model_service


class Command(BaseCommand):
    help = 'Executes model evaluation benchmark on all 60 official sample plates from Samples/labels.csv'

    def handle(self, *args, **options):
        samples_dir = Path(settings.BASE_DIR) / 'Samples'
        labels_csv = samples_dir / 'labels.csv'

        if not labels_csv.exists():
            self.stderr.write(self.style.ERROR(f"Labels file not found at {labels_csv}"))
            return

        service = get_model_service()
        self.stdout.write(self.style.NOTICE(f"Running evaluation with model: {service.MODEL_NAME}"))

        tp = 0  # GT: Defective, Pred: Defective
        tn = 0  # GT: Normal, Pred: Normal
        fp = 0  # GT: Normal, Pred: Defective
        fn = 0  # GT: Defective, Pred: Normal
        failed = 0
        detailed_results = []

        with open(labels_csv, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                img_rel = row['relative_path']
                img_path = samples_dir / img_rel
                gt_label = row['label'].strip()

                try:
                    res = service.classify_image(img_path)
                    pred_label = res['predicted_class']
                    conf = res['confidence']

                    if gt_label == 'Defective' and pred_label == 'Defective':
                        tp += 1
                        match = True
                    elif gt_label == 'Normal' and pred_label == 'Normal':
                        tn += 1
                        match = True
                    elif gt_label == 'Normal' and pred_label == 'Defective':
                        fp += 1
                        match = False
                    elif gt_label == 'Defective' and pred_label == 'Normal':
                        fn += 1
                        match = False
                    else:
                        match = False

                    detailed_results.append({
                        'image_id': row.get('image_id', img_rel),
                        'path': img_rel,
                        'ground_truth': gt_label,
                        'predicted': pred_label,
                        'confidence': conf,
                        'match': match,
                    })
                except Exception as err:
                    failed += 1
                    detailed_results.append({
                        'image_id': row.get('image_id', img_rel),
                        'path': img_rel,
                        'ground_truth': gt_label,
                        'predicted': 'FAILED',
                        'error': str(err),
                        'match': False,
                    })

        total_valid = tp + tn + fp + fn
        accuracy = (tp + tn) / total_valid if total_valid > 0 else 0.0
        defect_recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        defect_precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        f1 = (2 * defect_precision * defect_recall) / (defect_precision + defect_recall) if (defect_precision + defect_recall) > 0 else 0.0

        confusion_matrix = {
            'matrix': [[tn, fp], [fn, tp]],
            'labels': ['Normal', 'Defective'],
            'TN': tn,
            'FP': fp,
            'FN': fn,
            'TP': tp,
        }

        run = ModelEvaluationRun.objects.create(
            model_version=service.MODEL_NAME,
            total_samples=len(detailed_results),
            true_positives=tp,
            true_negatives=tn,
            false_positives=fp,
            false_negatives=fn,
            failed_predictions=failed,
            accuracy=round(accuracy, 4),
            defect_recall=round(defect_recall, 4),
            defect_precision=round(defect_precision, 4),
            f1_score=round(f1, 4),
            confusion_matrix_json=confusion_matrix,
            detailed_results_json=detailed_results,
        )

        # Output Results to Console
        self.stdout.write(self.style.SUCCESS("\n" + "=" * 60))
        self.stdout.write(self.style.SUCCESS("  INOVEX — MODEL BENCHMARK EVALUATION"))
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(f"Model Version:         {run.model_version}")
        self.stdout.write(f"Total Samples:         {run.total_samples} (30 Normal, 30 Defective)")
        self.stdout.write(f"Failed Predictions:    {run.failed_predictions}")
        self.stdout.write(f"True Positives (TP):   {run.true_positives}")
        self.stdout.write(f"True Negatives (TN):   {run.true_negatives}")
        self.stdout.write(f"False Positives (FP):  {run.false_positives}")
        self.stdout.write(f"False Negatives (FN):  {run.false_negatives}")
        self.stdout.write(f"Accuracy:              {run.accuracy:.2%} ({(tp + tn)}/{total_valid})")
        self.stdout.write(f"Defect Recall:         {run.defect_recall:.2%} ({tp}/{tp + fn})")
        self.stdout.write(f"Defect Precision:      {run.defect_precision:.2%} ({tp}/{tp + fp})")
        self.stdout.write(f"F1 Score:              {run.f1_score:.4f}")

        self.stdout.write("\nCONFUSION MATRIX (Order: Normal, Defective):")
        self.stdout.write("-" * 50)
        self.stdout.write(f"{'Actual \\ Predicted':<20} | {'Normal':<12} | {'Defective':<12}")
        self.stdout.write("-" * 50)
        self.stdout.write(f"{'Actual Normal':<20} | {tn:<12} (TN) | {fp:<12} (FP)")
        self.stdout.write(f"{'Actual Defective':<20} | {fn:<12} (FN) | {tp:<12} (TP)")
        self.stdout.write("-" * 50)

        if fn == 0:
            self.stdout.write(self.style.WARNING("\n[NOTICE ON ZERO FALSE NEGATIVES]:"))
            self.stdout.write(self.style.WARNING(
                "Although the model achieves 100% Defect Recall (0 False Negatives) on this\n"
                "60-sample synthetic benchmark, this small synthetic dataset cannot establish\n"
                "real-world manufacturing reliability due to constrained surface variance,\n"
                "constant synthetic lighting, and lack of line noise. Human supervisor review\n"
                "remains essential for factory deployment."
            ))
        self.stdout.write(self.style.SUCCESS("=" * 60 + "\n"))
