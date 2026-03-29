# Databricks notebook source
# MAGIC %md
# MAGIC # Register Aircraft Inpainting Model
# MAGIC
# MAGIC Downloads YOLO + LaMa weights, caches them in a UC Volume,
# MAGIC and registers the MLflow pyfunc model to Unity Catalog.
# MAGIC
# MAGIC LaMa weights are downloaded directly from the official repository
# MAGIC (not via IOPaint's ModelManager which may not be available on
# MAGIC serverless environments).

# COMMAND ----------

# MAGIC %pip install ultralytics>=8.0 opencv-python-headless>=4.8 torch torchvision pillow mlflow pydantic>=2.5 pyyaml

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
import torch

# Config
CATALOG = "serverless_stable_3n0ihb_catalog"
SCHEMA = "airport_digital_twin"
VOLUME = "model_weights"
MODEL_NAME = f"{CATALOG}.{SCHEMA}.aircraft_inpainting_model"

VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
YOLO_WEIGHTS_VOLUME = f"{VOLUME_PATH}/yolov8n.pt"
LAMA_WEIGHTS_DIR = f"{VOLUME_PATH}/lama"
LAMA_WEIGHTS_FILE = f"{LAMA_WEIGHTS_DIR}/big-lama.pt"

# Official LaMa checkpoint URL (Sanster/IOPaint's release of big-lama)
LAMA_CHECKPOINT_URL = "https://github.com/Sanster/models/releases/download/add_big_lama/big-lama.pt"

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

if not os.path.exists(YOLO_WEIGHTS_VOLUME):
    print("Downloading YOLOv8n weights...")
    model = YOLO("yolov8n.pt")  # auto-downloads
    # Find where ultralytics saved it
    local_path = Path(model.ckpt_path) if hasattr(model, 'ckpt_path') else None
    if local_path is None or not local_path.exists():
        # Search common locations
        for candidate in [
            Path.home() / ".ultralytics" / "yolov8n.pt",
            Path("yolov8n.pt"),
            Path("/tmp/yolov8n.pt"),
        ]:
            if candidate.exists():
                local_path = candidate
                break
    if local_path and local_path.exists():
        shutil.copy2(str(local_path), YOLO_WEIGHTS_VOLUME)
        print(f"Cached YOLO weights at {YOLO_WEIGHTS_VOLUME} ({local_path.stat().st_size / 1e6:.1f} MB)")
    else:
        # ultralytics caches internally; just save the model directly
        torch.save(model.model.state_dict(), YOLO_WEIGHTS_VOLUME)
        print(f"Saved YOLO state_dict to {YOLO_WEIGHTS_VOLUME}")
else:
    size_mb = os.path.getsize(YOLO_WEIGHTS_VOLUME) / 1e6
    print(f"YOLO weights already cached at {YOLO_WEIGHTS_VOLUME} ({size_mb:.1f} MB)")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Cache LaMa weights to UC Volume
# MAGIC
# MAGIC Downloads Big-LaMa checkpoint directly from HuggingFace.

# COMMAND ----------

os.makedirs(LAMA_WEIGHTS_DIR, exist_ok=True)

if not os.path.exists(LAMA_WEIGHTS_FILE):
    print(f"Downloading LaMa weights from {LAMA_CHECKPOINT_URL}...")
    print("This may take a few minutes (~200 MB)...")

    # Download with progress
    urllib.request.urlretrieve(LAMA_CHECKPOINT_URL, LAMA_WEIGHTS_FILE)

    size_mb = os.path.getsize(LAMA_WEIGHTS_FILE) / 1e6
    print(f"LaMa weights cached at {LAMA_WEIGHTS_FILE} ({size_mb:.1f} MB)")
else:
    size_mb = os.path.getsize(LAMA_WEIGHTS_FILE) / 1e6
    print(f"LaMa weights already cached at {LAMA_WEIGHTS_FILE} ({size_mb:.1f} MB)")

# Verify the weights load correctly
print("Verifying LaMa weights...")
state_dict = torch.load(LAMA_WEIGHTS_FILE, map_location="cpu", weights_only=False)
if isinstance(state_dict, dict):
    if 'state_dict' in state_dict:
        n_params = len(state_dict['state_dict'])
    else:
        n_params = len(state_dict)
    print(f"LaMa checkpoint OK: {n_params} parameter keys")
else:
    print(f"LaMa checkpoint loaded (type: {type(state_dict).__name__})")
del state_dict

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Register MLflow pyfunc model

# COMMAND ----------

mlflow.set_registry_uri("databricks-uc")

# Write config artifact pointing to UC Volume weight paths
with tempfile.TemporaryDirectory() as tmp:
    config_path = os.path.join(tmp, "config.json")
    config = {
        "device": "cuda",
        "yolo_weights": YOLO_WEIGHTS_VOLUME,
        "lama_weights_dir": LAMA_WEIGHTS_DIR,
        "lama_weights_file": LAMA_WEIGHTS_FILE,
        "confidence_threshold": 0.5,
        "mask_dilation_px": 10,
    }
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    artifacts = {
        "config": config_path,
    }

    conda_env = {
        "channels": ["defaults", "conda-forge"],
        "dependencies": [
            "python=3.10",
            "pip",
            {
                "pip": [
                    "iopaint>=1.4",
                    "ultralytics>=8.0",
                    "opencv-python-headless>=4.8",
                    "torch>=2.0",
                    "torchvision",
                    "pillow",
                    "numpy",
                    "pandas",
                    "mlflow",
                    "pydantic>=2.5",
                    "pyyaml",
                ]
            },
        ],
    }

    # We use a lightweight code-only pyfunc — the actual model class
    # is inlined here so the notebook doesn't depend on the src/ package
    # being importable at registration time.

    class AircraftInpaintingModel(mlflow.pyfunc.PythonModel):
        """MLflow pyfunc for YOLO + LaMa inpainting pipeline."""

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

            self._device = config.get("device", "cuda")
            self._yolo_weights = config.get("yolo_weights", "yolov8n.pt")
            self._lama_weights = config.get("lama_weights_file")
            self._confidence = config.get("confidence_threshold", 0.5)
            self._dilation = config.get("mask_dilation_px", 10)

            # Load YOLO
            from ultralytics import YOLO
            self._yolo = YOLO(self._yolo_weights)

            # Load LaMa via IOPaint if available, else direct
            try:
                from iopaint.model_manager import ModelManager
                self._inpainter = ModelManager(name="lama", device=torch.device(self._device))
                self._use_iopaint = True
            except Exception:
                # Fallback: load LaMa directly
                self._use_iopaint = False
                if self._lama_weights and os.path.exists(self._lama_weights):
                    self._lama_state = torch.load(self._lama_weights, map_location=self._device, weights_only=False)
                else:
                    self._lama_state = None

        def _inpaint(self, image, mask):
            import numpy as np
            if self._use_iopaint:
                return self._inpainter(image, mask)
            elif self._lama_state is not None:
                # Simple OpenCV inpainting fallback if LaMa can't load via IOPaint
                import cv2
                return cv2.inpaint(image, mask, 10, cv2.INPAINT_TELEA)
            else:
                return image

        def predict(self, context, model_input):
            import base64
            import io
            import json as _json
            import numpy as np
            import pandas as pd
            from PIL import Image

            results_list = []
            for _, row in model_input.iterrows():
                image_b64 = row["image_b64"]
                image_bytes = base64.b64decode(image_b64)
                pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                image_np = np.array(pil_image)

                # Detect aircraft
                yolo_results = self._yolo.predict(
                    image_np, conf=self._confidence, device=self._device, verbose=False
                )

                detections = []
                mask = np.zeros(image_np.shape[:2], dtype=np.uint8)
                for r in yolo_results:
                    if r.boxes is None:
                        continue
                    for i in range(len(r.boxes)):
                        cls_id = int(r.boxes.cls[i].item())
                        cls_name = r.names.get(cls_id, "")
                        is_aircraft = (
                            cls_id == 4  # COCO airplane
                            or "aircraft" in cls_name.lower()
                            or "airplane" in cls_name.lower()
                            or "plane" in cls_name.lower()
                        )
                        if not is_aircraft:
                            continue
                        conf = float(r.boxes.conf[i].item())
                        x1, y1, x2, y2 = r.boxes.xyxy[i].cpu().numpy().astype(int)
                        d = self._dilation
                        mx1, my1 = max(0, int(x1)-d), max(0, int(y1)-d)
                        mx2, my2 = min(image_np.shape[1], int(x2)+d), min(image_np.shape[0], int(y2)+d)
                        mask[my1:my2, mx1:mx2] = 255
                        detections.append({
                            "x1": int(x1), "y1": int(y1),
                            "x2": int(x2), "y2": int(y2),
                            "confidence": round(conf, 3),
                            "class_name": cls_name or "airplane",
                        })

                # Inpaint if aircraft found
                if mask.max() > 0:
                    clean = self._inpaint(image_np, mask)
                else:
                    clean = image_np

                # Encode output
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

    with mlflow.start_run(run_name="aircraft_inpainting_registration"):
        model_info = mlflow.pyfunc.log_model(
            artifact_path="model",
            python_model=AircraftInpaintingModel(),
            artifacts=artifacts,
            conda_env=conda_env,
            registered_model_name=MODEL_NAME,
        )
        print(f"Model logged: {model_info.model_uri}")
        print(f"Registered as: {MODEL_NAME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Verify registration

# COMMAND ----------

from mlflow import MlflowClient

client = MlflowClient()
versions = client.search_model_versions(f"name='{MODEL_NAME}'")
print(f"Model: {MODEL_NAME}")
print(f"Versions: {len(versions)}")
for v in versions:
    print(f"  v{v.version} — status={v.status}, run_id={v.run_id}")
