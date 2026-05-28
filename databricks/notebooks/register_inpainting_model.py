# Databricks notebook source
# MAGIC %md
# MAGIC # Register Aircraft Inpainting Model
# MAGIC
# MAGIC Downloads YOLO OBB weights, caches them in a UC Volume,
# MAGIC and registers the MLflow pyfunc model to Unity Catalog.
# MAGIC
# MAGIC Uses cv2 TELEA inpainting (no LaMa/torch-heavy deps) for
# MAGIC GPU serving compatibility.

# COMMAND ----------

# MAGIC %pip install ultralytics>=8.3 opencv-python-headless>=4.8 torch pillow mlflow pydantic>=2.5 pyyaml

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import json
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path

import mlflow
import torch  # noqa: F401 — used inside model class at serving time

# Config — parameterized via job base_parameters (defaults for interactive use)
dbutils.widgets.text("catalog", "serverless_stable_3n0ihb_catalog")
dbutils.widgets.text("schema", "airport_digital_twin")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
VOLUME = "model_weights"
MODEL_NAME = f"{CATALOG}.{SCHEMA}.aircraft_inpainting_model"

VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
YOLO_WEIGHTS_VOLUME = f"{VOLUME_PATH}/yolov8s-obb.pt"

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Ensure UC Volume exists

# COMMAND ----------

spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{VOLUME}")
print(f"Volume ready: {VOLUME_PATH}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Cache YOLO weights to UC Volume

# COMMAND ----------

from ultralytics import YOLO

YOLO_OBB_URL = "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolov8s-obb.pt"

# Always re-download to ensure latest version (v8.4.0)
print("Downloading YOLOv8s-OBB weights (DOTA satellite aircraft detection, v8.4.0)...")
local_path = Path("/tmp/yolov8s-obb.pt")
urllib.request.urlretrieve(YOLO_OBB_URL, str(local_path))
shutil.copy2(str(local_path), YOLO_WEIGHTS_VOLUME)
print(f"Cached YOLO OBB weights at {YOLO_WEIGHTS_VOLUME} ({local_path.stat().st_size / 1e6:.1f} MB)")

# Verify it loads and detects correctly
model = YOLO(YOLO_WEIGHTS_VOLUME)
print(f"YOLO OBB model loaded: {len(model.names)} classes, task={model.task}")
print(f"Classes: {model.names}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Register MLflow pyfunc model
# MAGIC
# MAGIC Uses cv2 TELEA inpainting — minimal deps, GPU-serving compatible.

# COMMAND ----------

mlflow.set_registry_uri("databricks-uc")

with tempfile.TemporaryDirectory() as tmp:
    config_path = os.path.join(tmp, "config.json")
    config = {
        "device": "auto",
        "yolo_weights": YOLO_WEIGHTS_VOLUME,
        "confidence_threshold": 0.25,
        "mask_dilation_px": 10,
        "max_detection_ratio": 0.03,
        "imgsz": 640,
    }
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    artifacts = {"config": config_path}

    pip_requirements = [
        "ultralytics>=8.3",
        "opencv-python-headless>=4.8",
        "pillow",
        "numpy",
        "pandas",
        "pydantic>=2.5",
        "pyyaml",
    ]

    class AircraftInpaintingModel(mlflow.pyfunc.PythonModel):
        """MLflow pyfunc: YOLO OBB detection + cv2 TELEA inpainting."""

        def load_context(self, context):
            import json as _json

            config = {}
            try:
                config_path = context.artifacts.get("config")
                if config_path:
                    with open(config_path) as f:
                        config = _json.load(f)
            except Exception:
                pass

            if torch.cuda.is_available():
                self._device = "cuda"
            else:
                self._device = "cpu"

            self._yolo_weights = config.get("yolo_weights", "yolov8n.pt")
            self._confidence = config.get("confidence_threshold", 0.25)
            self._dilation = config.get("mask_dilation_px", 10)
            self._max_det_ratio = config.get("max_detection_ratio", 0.03)
            self._imgsz = config.get("imgsz", 640)

            from ultralytics import YOLO
            self._yolo = YOLO(self._yolo_weights)
            print(f"YOLO OBB loaded (device={self._device}, imgsz={self._imgsz}, conf={self._confidence})")

        def predict(self, context, model_input):
            import base64
            import io
            import json as _json
            import cv2
            import numpy as np
            import pandas as pd
            from PIL import Image

            results_list = []
            for _, row in model_input.iterrows():
                image_b64 = row["image_b64"]
                image_bytes = base64.b64decode(image_b64)
                pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                image_np = np.array(pil_image)

                yolo_results = self._yolo.predict(
                    image_np, conf=self._confidence, device=self._device,
                    imgsz=self._imgsz, verbose=False
                )

                detections = []
                for r in yolo_results:
                    obb = getattr(r, 'obb', None)
                    if obb is not None and len(obb) > 0:
                        for i in range(len(obb)):
                            cls_id = int(obb.cls[i].item())
                            cls_name = r.names.get(cls_id, "")
                            is_aircraft = (
                                cls_id == 0
                                or "plane" in cls_name.lower()
                                or "aircraft" in cls_name.lower()
                            )
                            if not is_aircraft:
                                continue
                            conf = float(obb.conf[i].item())
                            corners = obb.xyxyxyxy[i].cpu().numpy().astype(np.int32)
                            x1, y1 = corners.min(axis=0)
                            x2, y2 = corners.max(axis=0)
                            detections.append({
                                "x1": int(x1), "y1": int(y1),
                                "x2": int(x2), "y2": int(y2),
                                "confidence": round(conf, 3),
                                "class_name": cls_name or "plane",
                                "_corners": corners,
                            })
                    elif r.boxes is not None and len(r.boxes) > 0:
                        for i in range(len(r.boxes)):
                            cls_id = int(r.boxes.cls[i].item())
                            cls_name = r.names.get(cls_id, "")
                            is_aircraft = (
                                cls_id == 4
                                or "plane" in cls_name.lower()
                                or "aircraft" in cls_name.lower()
                            )
                            if not is_aircraft:
                                continue
                            conf = float(r.boxes.conf[i].item())
                            x1, y1, x2, y2 = r.boxes.xyxy[i].cpu().numpy().astype(int)
                            detections.append({
                                "x1": int(x1), "y1": int(y1),
                                "x2": int(x2), "y2": int(y2),
                                "confidence": round(conf, 3),
                                "class_name": cls_name or "plane",
                            })

                tile_area = image_np.shape[0] * image_np.shape[1]
                max_area = self._max_det_ratio * tile_area
                detections = [
                    d for d in detections
                    if (d["x2"] - d["x1"]) * (d["y2"] - d["y1"]) < max_area
                ]

                mask = np.zeros(image_np.shape[:2], dtype=np.uint8)
                for det in detections:
                    corners = det.pop("_corners", None)
                    if corners is not None:
                        center = corners.mean(axis=0)
                        scale = 1 + self._dilation / 60.0
                        expanded = (center + (corners - center) * scale).astype(np.int32)
                        cv2.fillPoly(mask, [expanded], 255)
                    else:
                        x1, y1 = det["x1"], det["y1"]
                        x2, y2 = det["x2"], det["y2"]
                        d = self._dilation
                        mx1, my1 = max(0, x1 - d), max(0, y1 - d)
                        mx2 = min(image_np.shape[1], x2 + d)
                        my2 = min(image_np.shape[0], y2 + d)
                        mask[my1:my2, mx1:mx2] = 255

                total_pixels = mask.shape[0] * mask.shape[1]
                mask_ratio = np.count_nonzero(mask) / total_pixels
                if mask_ratio > 0.15:
                    clean = image_np
                    detections = []
                elif mask.max() > 0:
                    clean = cv2.inpaint(image_np, mask, 10, cv2.INPAINT_TELEA)
                else:
                    clean = image_np

                out_pil = Image.fromarray(clean)
                buf = io.BytesIO()
                out_pil.save(buf, format="PNG")
                out_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

                results_list.append({
                    "clean_image_b64": out_b64,
                    "aircraft_count": len(detections),
                    "detections": _json.dumps(detections),
                })

            return pd.DataFrame(results_list)

    from mlflow.models.signature import ModelSignature
    from mlflow.types.schema import ColSpec, Schema

    input_schema = Schema([ColSpec("string", "image_b64")])
    output_schema = Schema([
        ColSpec("string", "clean_image_b64"),
        ColSpec("long", "aircraft_count"),
        ColSpec("string", "detections"),
    ])
    signature = ModelSignature(inputs=input_schema, outputs=output_schema)

    with mlflow.start_run(run_name="aircraft_inpainting_registration"):
        model_info = mlflow.pyfunc.log_model(
            artifact_path="model",
            python_model=AircraftInpaintingModel(),
            artifacts=artifacts,
            pip_requirements=pip_requirements,
            signature=signature,
            registered_model_name=MODEL_NAME,
        )
        print(f"Model logged: {model_info.model_uri}")
        print(f"Registered as: {MODEL_NAME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Verify registration

# COMMAND ----------

from mlflow import MlflowClient

client = MlflowClient()
versions = client.search_model_versions(f"name='{MODEL_NAME}'")
print(f"Model: {MODEL_NAME}")
print(f"Versions: {len(versions)}")
for v in versions:
    print(f"  v{v.version} — status={v.status}, run_id={v.run_id}")
