import os
import sys
import importlib.util
from pathlib import Path
from typing import Dict, Any, Union
from django.conf import settings
from PIL import UnidentifiedImageError


class ModelIntegrationError(Exception):
    """Base exception for model loading and prediction errors."""
    pass


class ModelNotFoundError(ModelIntegrationError):
    """Raised when model weights or inference script are missing."""
    pass


class InvalidImageError(ModelIntegrationError):
    """Raised when the target image cannot be opened or parsed."""
    pass


class QualityInspectionModelService:
    """
    Model integration service encapsulating the supplied pretrained vision classifier:
    - Model Name: BIT-PLATE-CV-1.0
    - Target Product: P-PLATE01
    - Frozen architecture: 17 standardized spatial & quantile feature metrics + logistic regression
    - Decision threshold: 0.5 (fixed)
    """

    MODEL_NAME = "BIT-PLATE-CV-1.0"
    PRODUCT_ID = "P-PLATE01"
    DECISION_THRESHOLD = 0.5

    def __init__(self, model_dir: Union[str, Path] = None):
        if model_dir is None:
            try:
                self.model_dir = Path(settings.BASE_DIR) / "Model"
            except Exception:
                self.model_dir = Path(__file__).resolve().parent.parent.parent / "Model"
        else:
            self.model_dir = Path(model_dir)

        self.inference_script_path = self.model_dir / "inference.py"
        self.classifier_weights_path = self.model_dir / "classifier.npz"

        self._predict_fn = None
        self._load_supplied_module()

    def _load_supplied_module(self):
        """
        Dynamically imports the predict function from the original supplied inference.py
        without modifying or relocating the original model files.
        """
        if not self.inference_script_path.exists():
            raise ModelNotFoundError(
                f"Supplied inference script not found at expected path: {self.inference_script_path}"
            )

        if not self.classifier_weights_path.exists():
            raise ModelNotFoundError(
                f"Supplied model weights not found at expected path: {self.classifier_weights_path}"
            )

        try:
            spec = importlib.util.spec_from_file_location(
                "supplied_bit_plate_inference",
                str(self.inference_script_path)
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if not hasattr(module, "predict"):
                raise ModelIntegrationError("Supplied inference.py does not define a 'predict' function.")

            self._predict_fn = module.predict
        except Exception as exc:
            if isinstance(exc, ModelIntegrationError):
                raise
            raise ModelIntegrationError(f"Failed to load supplied inference module: {exc}") from exc

    def classify_image(self, image_path: Union[str, Path]) -> Dict[str, Any]:
        """
        Executes local inference on the supplied image file using the frozen classifier.

        Returns a dictionary with:
        - predicted_class: "Normal" or "Defective"
        - confidence: float between 0.5 and 1.0
        - defect_probability: float between 0.0 and 1.0
        - model_version: "BIT-PLATE-CV-1.0"
        - decision_threshold: 0.5
        """
        img_path = Path(image_path)
        if not img_path.exists():
            raise FileNotFoundError(f"Inspection image file does not exist: {img_path}")

        try:
            # Pass explicit path to the original frozen classifier.npz weights
            raw_result = self._predict_fn(str(img_path), model_path=str(self.classifier_weights_path))
        except (UnidentifiedImageError, OSError) as img_err:
            raise InvalidImageError(f"Cannot decode inspection image at '{img_path}': {img_err}") from img_err
        except Exception as exc:
            raise ModelIntegrationError(f"Inference execution failed on '{img_path}': {exc}") from exc

        # Extract and validate required output fields
        raw_class = raw_result.get("predicted_class")
        confidence = float(raw_result.get("confidence", 0.0))
        defect_probability = float(raw_result.get("defect_probability", 0.0))
        model_version = str(raw_result.get("model_version", self.MODEL_NAME))

        # Explicit Class 0 -> 'Normal' / Class 1 -> 'Defective' conversion mapping
        class_mapping = {
            0: "Normal",
            1: "Defective",
            "0": "Normal",
            "1": "Defective",
            "Normal": "Normal",
            "Defective": "Defective",
        }
        normalized_class = class_mapping.get(raw_class, "Normal" if defect_probability < self.DECISION_THRESHOLD else "Defective")

        return {
            "predicted_class": normalized_class,
            "confidence": round(confidence, 6),
            "defect_probability": round(defect_probability, 6),
            "model_version": model_version,
            "decision_threshold": self.DECISION_THRESHOLD,
        }


# Singleton service instance accessor
_service_instance = None

def get_model_service() -> QualityInspectionModelService:
    global _service_instance
    if _service_instance is None:
        _service_instance = QualityInspectionModelService()
    return _service_instance
