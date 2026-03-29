# Databricks notebook source
# MAGIC %md
# MAGIC # Register Aircraft Inpainting Model
# MAGIC
# MAGIC Downloads YOLO + LaMa weights, caches them in a UC Volume,
# MAGIC and registers the MLflow pyfunc model to Unity Catalog.

# COMMAND ----------

# MAGIC %pip install iopaint>=1.4 ultralytics>=8.0 opencv-python-headless>=4.8 torch torchvision pillow

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

import json
import os
import tempfile
from pathlib import Path

import mlflow

# Config
CATALOG = "serverless_stable_3n0ihb_catalog"
SCHEMA = "airport_digital_twin"
VOLUME = "model_weights"
MODEL_NAME = f"{CATALOG}.{SCHEMA}.aircraft_inpainting_model"

VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
YOLO_WEIGHTS_VOLUME = f"{VOLUME_PATH}/yolov8n.pt"
LAMA_WEIGHTS_DIR = f"{VOLUME_PATH}/lama"

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
    model = YOLO("yolov8n.pt")  # auto-downloads to ~/.ultralytics/
    # Copy to UC Volume
    import shutil
    local_path = Path.home() / ".ultralytics" / "yolov8n.pt"
    if not local_path.exists():
        # Fallback: ultralytics may store in a different location
        local_path = Path(model.ckpt_path)
    shutil.copy2(str(local_path), YOLO_WEIGHTS_VOLUME)
    print(f"Cached YOLO weights at {YOLO_WEIGHTS_VOLUME}")
else:
    print(f"YOLO weights already cached at {YOLO_WEIGHTS_VOLUME}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Cache LaMa weights to UC Volume
# MAGIC
# MAGIC IOPaint auto-downloads LaMa weights on first use.
# MAGIC We trigger this once and copy to the Volume.

# COMMAND ----------

import torch
from iopaint.model_manager import ModelManager

os.makedirs(LAMA_WEIGHTS_DIR, exist_ok=True)

if not os.listdir(LAMA_WEIGHTS_DIR):
    print("Downloading LaMa weights via IOPaint...")
    # This triggers the download
    _model = ModelManager(name="lama", device=torch.device("cpu"))
    del _model

    # IOPaint caches in ~/.cache/torch/hub/checkpoints or similar
    # Copy the weights to our UC Volume
    import shutil
    iopaint_cache = Path.home() / ".cache" / "torch" / "hub" / "checkpoints"
    for f in iopaint_cache.glob("*lama*"):
        shutil.copy2(str(f), LAMA_WEIGHTS_DIR)
        print(f"Cached {f.name} -> {LAMA_WEIGHTS_DIR}")
    print(f"LaMa weights cached at {LAMA_WEIGHTS_DIR}")
else:
    print(f"LaMa weights already cached at {LAMA_WEIGHTS_DIR}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Register MLflow pyfunc model

# COMMAND ----------

mlflow.set_registry_uri("databricks-uc")

# Write config artifact
with tempfile.TemporaryDirectory() as tmp:
    config_path = os.path.join(tmp, "config.json")
    config = {
        "device": "cuda",
        "yolo_weights": YOLO_WEIGHTS_VOLUME,
        "lama_weights_dir": LAMA_WEIGHTS_DIR,
        "confidence_threshold": 0.5,
        "mask_dilation_px": 10,
    }
    with open(config_path, "w") as f:
        json.dump(config, f)

    artifacts = {
        "config": config_path,
        "yolo_weights": YOLO_WEIGHTS_VOLUME,
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
                ]
            },
        ],
    }

    # Import the pyfunc model class
    from src.ml.inpainting.serving import AircraftInpaintingModel

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
