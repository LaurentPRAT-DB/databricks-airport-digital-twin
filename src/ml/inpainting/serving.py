"""MLflow pyfunc model for aircraft inpainting on Databricks Model Serving.

Wraps the InpaintingPipeline as a serving-friendly model that accepts
base64-encoded satellite tiles and returns clean tiles.
"""

import base64
import io
import json
import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class AircraftInpaintingModel:
    """MLflow pyfunc-compatible model for the YOLO + LaMa inpainting pipeline.

    Usage with MLflow:
        import mlflow
        mlflow.pyfunc.log_model(
            artifact_path="model",
            python_model=AircraftInpaintingModel(),
            ...
        )

    Input format (via serving endpoint):
        {"dataframe_split": {"columns": ["image_b64"], "data": [["<base64>"]]}}

    Output:
        {"columns": ["clean_image_b64", "aircraft_count", "detections"],
         "data": [["<base64>", 3, "[{...}]"]]}
    """

    def load_context(self, context: Any) -> None:
        """Called when the model is loaded by the serving endpoint.

        Reads configuration from the MLflow model artifacts to locate
        YOLO and LaMa weights (typically in a UC Volume).
        """
        from src.ml.inpainting.pipeline import InpaintingPipeline

        # Read config from artifacts if available
        config = {}
        try:
            config_path = context.artifacts.get("config")
            if config_path:
                with open(config_path) as f:
                    config = json.load(f)
        except Exception:
            logger.info("No config artifact found, using defaults")

        device = config.get("device", "cuda")
        yolo_weights = config.get("yolo_weights")
        lama_weights_dir = config.get("lama_weights_dir")
        confidence = config.get("confidence_threshold", 0.5)
        dilation = config.get("mask_dilation_px", 10)

        # Resolve UC Volume paths from artifacts
        if not yolo_weights:
            yolo_path = context.artifacts.get("yolo_weights")
            if yolo_path:
                yolo_weights = yolo_path

        self.pipeline = InpaintingPipeline(
            yolo_weights=yolo_weights,
            confidence_threshold=confidence,
            mask_dilation_px=dilation,
            device=device,
            lama_weights_dir=lama_weights_dir,
        )
        logger.info("AircraftInpaintingModel loaded (device=%s)", device)

    def predict(self, context: Any, model_input: pd.DataFrame) -> pd.DataFrame:
        """Process base64-encoded satellite tile images.

        Args:
            context: MLflow context (unused in predict).
            model_input: DataFrame with column 'image_b64' containing
                         base64-encoded PNG/JPEG satellite tile images.

        Returns:
            DataFrame with columns:
              - clean_image_b64: base64-encoded inpainted PNG
              - aircraft_count: number of aircraft detected and removed
              - detections: JSON array of detection bounding boxes
        """
        from PIL import Image

        results: List[Dict[str, Any]] = []

        for _, row in model_input.iterrows():
            image_b64 = row["image_b64"]

            # Decode input
            image_bytes = base64.b64decode(image_b64)
            pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            image_np = np.array(pil_image)

            # Run pipeline
            result = self.pipeline.remove_aircraft(image_np)

            # Encode output
            out_pil = Image.fromarray(result.image)
            buf = io.BytesIO()
            out_pil.save(buf, format="PNG")
            out_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

            detections_json = json.dumps(
                [
                    {
                        "x1": d.x1,
                        "y1": d.y1,
                        "x2": d.x2,
                        "y2": d.y2,
                        "confidence": round(d.confidence, 3),
                        "class_name": d.class_name,
                    }
                    for d in result.detections
                ]
            )

            results.append(
                {
                    "clean_image_b64": out_b64,
                    "aircraft_count": result.aircraft_count,
                    "detections": detections_json,
                }
            )

        return pd.DataFrame(results)
