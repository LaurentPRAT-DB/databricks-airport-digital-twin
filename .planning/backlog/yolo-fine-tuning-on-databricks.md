# Fine-Tuning YOLO for Satellite Aircraft Detection on Databricks

## Current State

The inpainting pipeline uses **YOLOv8s-OBB** (pre-trained on DOTA aerial dataset). Results on zoom-17 Esri satellite tiles:

| Metric | Value |
|--------|-------|
| Airports tested | 9 |
| Total aircraft detected | 34 |
| Avg latency | 2.3s |
| Detection quality | Moderate — misses some aircraft, occasional false positives |
| Inpainting quality | Poor — `cv2.INPAINT_TELEA` fallback, not LaMa |

**Why fine-tune?** The DOTA pre-trained model was trained on diverse aerial imagery (GSD 0.1-2.0 m/px). Our tiles are exclusively Esri World Imagery at zoom 17 (~1.2 m/px) showing commercial aircraft at airports. A domain-specific model would:
- Detect more aircraft (better recall)
- Produce tighter oriented bounding boxes (better masks)
- Reduce false positives on ground vehicles, buildings, shadows

---

## Step 1: Build a Training Dataset

### 1a. Collect satellite tiles with aircraft

```python
# scripts/collect_training_tiles.py
"""
Collect satellite tiles from known gate areas across multiple airports.
Each tile is 256x256 px at zoom 17 (~1.2 m/px).
Target: 500-1000 tiles with aircraft, 200-500 negative tiles.
"""
import asyncio, httpx
from scripts.test_inpainting_endpoint import (
    TERMINAL_COORDS, lat_lon_to_tile, fetch_original_tile
)

# Generate a 3x3 grid of tiles around each terminal
# to capture gates, taxiways, and surrounding areas
ZOOM = 17
GRID_RADIUS = 2  # 5x5 grid per airport

async def collect():
    async with httpx.AsyncClient() as client:
        for iata, (lat, lon) in TERMINAL_COORDS.items():
            cx, cy = lat_lon_to_tile(lat, lon, ZOOM)
            for dx in range(-GRID_RADIUS, GRID_RADIUS + 1):
                for dy in range(-GRID_RADIUS, GRID_RADIUS + 1):
                    tile = await fetch_original_tile(client, ZOOM, cx+dx, cy+dy)
                    # Save to data/training/tiles/{iata}_{ZOOM}_{cx+dx}_{cy+dy}.png
```

**Volume estimate**: 9 airports x 25 tiles = 225 tiles. Add 10+ more airports for diversity = ~500+ tiles.

### 1b. Label with CVAT or Label Studio on Databricks

**Option A: CVAT on Databricks Apps**
```yaml
# Deploy CVAT as a Databricks App for annotation
# Team can label aircraft with oriented bounding boxes (OBB)
```

**Option B: Use the current OBB model as pre-annotator**
```python
# Run YOLOv8s-OBB on all tiles, export predictions as DOTA-format labels
# Human reviewers correct/add missing annotations in CVAT
# This bootstraps labeling — typically 3-5x faster than labeling from scratch
```

**Option C: Roboflow (fastest)**
- Upload tiles to Roboflow
- Use their auto-annotate with SAM
- Export in YOLO-OBB format
- Free tier: 10,000 images

### 1c. DOTA annotation format

Each image gets a `.txt` label file:
```
# x1 y1 x2 y2 x3 y3 x4 y4 category difficulty
174 65 243 72 238 112 169 105 plane 0
```

---

## Step 2: Fine-Tune YOLOv8-OBB on Databricks

### 2a. Databricks notebook for training

```python
# databricks/notebooks/train_aircraft_yolo.py
# Databricks notebook source

# COMMAND ----------
# MAGIC %md
# MAGIC # Fine-Tune YOLOv8-OBB for Satellite Aircraft Detection
# MAGIC
# MAGIC **Cluster**: GPU (g5.xlarge or better, 1x A10G)
# MAGIC **Runtime**: ML Runtime 15.4+ (has PyTorch 2.x, CUDA)

# COMMAND ----------

# MAGIC %pip install ultralytics>=8.2.0 mlflow

# COMMAND ----------

import mlflow
from ultralytics import YOLO

# Config
CATALOG = "serverless_stable_3n0ihb_catalog"
SCHEMA = "airport_digital_twin"
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/model_weights"
DATASET_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/training_data/aircraft_obb"

# Start from pre-trained OBB model (transfer learning)
model = YOLO("yolov8s-obb.pt")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Dataset YAML
# MAGIC
# MAGIC Create a YAML file pointing to the training data:

# COMMAND ----------

import yaml, tempfile, os

dataset_config = {
    "path": DATASET_PATH,
    "train": "images/train",
    "val": "images/val",
    "names": {0: "plane"},  # Single class: aircraft from overhead
}

dataset_yaml = os.path.join(tempfile.mkdtemp(), "aircraft_obb.yaml")
with open(dataset_yaml, "w") as f:
    yaml.dump(dataset_config, f)

print(f"Dataset config: {dataset_yaml}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Training

# COMMAND ----------

with mlflow.start_run(run_name="aircraft_yolo_obb_finetune"):
    # Fine-tune with transfer learning
    results = model.train(
        data=dataset_yaml,
        epochs=100,          # 50-100 epochs for fine-tuning
        imgsz=640,           # Upscale from 256 for better detection
        batch=16,
        device=0,            # GPU
        lr0=0.001,           # Lower LR for fine-tuning (vs 0.01 default)
        lrf=0.01,
        warmup_epochs=5,

        # Augmentation (important for satellite imagery)
        mosaic=1.0,
        flipud=0.5,          # Vertical flip (overhead = rotation invariant)
        fliplr=0.5,          # Horizontal flip
        degrees=180,         # Full rotation (aircraft can face any direction)
        scale=0.5,           # Scale variation
        hsv_h=0.015,         # Color jitter (satellite imagery varies)
        hsv_s=0.5,
        hsv_v=0.3,

        # Save
        project=f"{VOLUME_PATH}/training_runs",
        name="aircraft_obb_v1",
    )

    # Log metrics
    mlflow.log_metrics({
        "mAP50": float(results.results_dict.get("metrics/mAP50(B)", 0)),
        "mAP50-95": float(results.results_dict.get("metrics/mAP50-95(B)", 0)),
        "precision": float(results.results_dict.get("metrics/precision(B)", 0)),
        "recall": float(results.results_dict.get("metrics/recall(B)", 0)),
    })

    # Log best weights as artifact
    best_weights = f"{VOLUME_PATH}/training_runs/aircraft_obb_v1/weights/best.pt"
    mlflow.log_artifact(best_weights)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Validation

# COMMAND ----------

# Validate on held-out set
val_results = model.val(data=dataset_yaml)
print(f"mAP50: {val_results.box.map50:.3f}")
print(f"mAP50-95: {val_results.box.map:.3f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Export and register

# COMMAND ----------

import shutil

# Copy best weights to UC Volume
best_pt = f"{VOLUME_PATH}/training_runs/aircraft_obb_v1/weights/best.pt"
target = f"{VOLUME_PATH}/yolov8s-obb-aircraft-v1.pt"
shutil.copy2(best_pt, target)
print(f"Fine-tuned weights saved to {target}")

# Update the inpainting model config to use the new weights
# Then re-run register_inpainting_model.py notebook
```

### 2b. Training hyperparameters rationale

| Parameter | Value | Why |
|-----------|-------|-----|
| `epochs` | 100 | Fine-tuning from pre-trained needs fewer epochs |
| `imgsz` | 640 | Upscale 256px tiles for better small-object detection |
| `lr0` | 0.001 | 10x lower than default — preserve pre-trained features |
| `degrees` | 180 | Aircraft can face any compass direction |
| `flipud` | 0.5 | Overhead imagery is rotation-invariant |
| `mosaic` | 1.0 | Combine tiles to simulate diverse backgrounds |

### 2c. Expected training time

| GPU | Tiles | Epochs | Time |
|-----|-------|--------|------|
| A10G (g5.xlarge) | 500 | 100 | ~30 min |
| A10G (g5.xlarge) | 2000 | 100 | ~2 hr |
| T4 (g4dn.xlarge) | 500 | 100 | ~1 hr |

---

## Step 3: Deploy Fine-Tuned Model

### 3a. Update registration notebook

In `databricks/notebooks/register_inpainting_model.py`:

```python
# Change the weights path to point to fine-tuned model
YOLO_WEIGHTS_VOLUME = f"{VOLUME_PATH}/yolov8s-obb-aircraft-v1.pt"
```

### 3b. Re-register and update endpoint

```bash
# 1. Deploy bundle with updated weights path
databricks bundle deploy --target dev

# 2. Re-register model (creates new version)
databricks bundle run inpainting_model_registration --target dev

# 3. Update serving endpoint to new version
databricks api put /api/2.0/serving-endpoints/airport-dt-aircraft-inpainting-dev/config \
  --json '{
    "served_entities": [{
      "entity_name": "serverless_stable_3n0ihb_catalog.airport_digital_twin.aircraft_inpainting_model",
      "entity_version": "N",
      "workload_size": "Small",
      "workload_type": "GPU_MEDIUM",
      "scale_to_zero_enabled": true
    }]
  }' --profile FEVM_SERVERLESS_STABLE

# 4. Run the test
uv run python scripts/test_inpainting_endpoint.py --direct --zoom 17
```

### 3c. A/B testing with aliases

```python
# Use UC model aliases for safe rollout
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()

# Set alias on new version
w.model_versions.set_alias(
    full_name="serverless_stable_3n0ihb_catalog.airport_digital_twin.aircraft_inpainting_model",
    version_num="5",
    alias="champion"
)

# Endpoint can reference alias instead of version number
# This allows instant rollback by changing the alias
```

---

## Step 4: Improve Inpainting Quality

The current `cv2.INPAINT_TELEA` fallback produces visible artifacts. Options:

### 4a. Get LaMa working via IOPaint

```python
# Add to conda_env in registration notebook
"iopaint>=1.3.0"

# The model already tries IOPaint first — if the package is available
# and LaMa weights download correctly, it will use proper neural inpainting
```

### 4b. Use Stable Diffusion inpainting

```python
# For highest quality, use SD inpainting model
from diffusers import StableDiffusionInpaintPipeline

pipe = StableDiffusionInpaintPipeline.from_pretrained(
    "stabilityai/stable-diffusion-2-inpainting"
)
result = pipe(
    prompt="satellite aerial view of airport tarmac, no aircraft",
    image=original_image,
    mask_image=mask,
).images[0]
```

### 4c. Increase `cv2.inpaint` radius

Quick win: increase the inpainting radius from 10 to 30-50px for better fill:
```python
cv2.inpaint(image, mask, 50, cv2.INPAINT_TELEA)
```

---

## Step 5: DABs Job Configuration

```yaml
# resources/yolo_training_job.yml
resources:
  jobs:
    aircraft_yolo_training:
      name: "[${bundle.target} ${workspace.current_user.short_name}] Airport DT - Aircraft YOLO Training"
      tasks:
        - task_key: train_yolo
          notebook_task:
            notebook_path: databricks/notebooks/train_aircraft_yolo.py
          new_cluster:
            spark_version: "15.4.x-gpu-ml-scala2.12"
            node_type_id: "g5.xlarge"
            num_workers: 0
            spark_conf:
              spark.master: "local[*]"
          libraries:
            - pypi:
                package: "ultralytics>=8.2.0"
```

---

## Summary: Full Pipeline

```
[Collect tiles] -> [Label in CVAT/Roboflow] -> [Upload to UC Volume]
       |                                              |
       v                                              v
[Fine-tune YOLOv8-OBB on GPU cluster] -> [Register in UC via MLflow]
                                              |
                                              v
                             [Update serving endpoint version]
                                              |
                                              v
                             [Test with test_inpainting_endpoint.py]
```

**Estimated effort**: 2-3 days (1 day labeling, 0.5 day training, 0.5 day deployment + tuning)
