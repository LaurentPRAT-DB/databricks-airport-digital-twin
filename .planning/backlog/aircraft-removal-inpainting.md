# Plan: Aircraft Removal from Satellite Imagery via Inpainting

## Context

The 3D view (`SatelliteGround.tsx`) renders Esri World Imagery tiles as the ground plane. These tiles often show parked aircraft, which conflicts with the simulated aircraft we overlay. We need a pipeline that:
1. Detects real aircraft in satellite tiles (YOLO)
2. Generates masks from detections
3. Inpaints the masked regions (LaMa via IOPaint) to produce clean airport infrastructure tiles

This will be deployed as a Databricks Model Serving endpoint on GPU_MEDIUM (T4), with LaMa weights cached in a UC Volume.

## Architecture

```
Satellite Tile (256x256)
  → YOLO aircraft detector → bounding box masks
  → IOPaint/LaMa inpainting → clean tile
  → return to caller
```

- **Serving endpoint:** Custom Python model (MLflow pyfunc) wrapping both YOLO + IOPaint.
- **Weight caching:** LaMa (~200MB) + YOLO weights stored in UC Volume `serverless_stable_3n0ihb_catalog.airport_digital_twin.model_weights`, loaded at container init (not re-downloaded on cold start).

## Files to Create

### 1. `src/ml/inpainting/` — Core inpainting module

- **`src/ml/inpainting/__init__.py`** — exports
- **`src/ml/inpainting/detector.py`** — YOLO aircraft detection
  - Uses ultralytics YOLOv8 with a pre-trained aerial/satellite model
  - `detect_aircraft(image: np.ndarray) -> list[BBox]`
  - Confidence threshold configurable (default 0.5)
  - Returns bounding boxes + confidence scores
- **`src/ml/inpainting/inpainter.py`** — IOPaint LaMa wrapper
  - `inpaint(image: np.ndarray, mask: np.ndarray) -> np.ndarray`
  - Loads LaMa model from local path (UC Volume or download)
  - Mask dilation option (expand bbox by N px for cleaner edges)
- **`src/ml/inpainting/pipeline.py`** — End-to-end pipeline
  - `remove_aircraft(image: np.ndarray) -> InpaintResult`
  - Orchestrates: detect → mask → inpaint
  - Returns: clean image + detection metadata (count, bboxes, confidence)
  - Handles edge case: no detections → return original image unchanged

### 2. `src/ml/inpainting/serving.py` — MLflow pyfunc model

- Custom `mlflow.pyfunc.PythonModel` wrapping the pipeline
- `load_context()`: loads YOLO + LaMa weights from UC Volume path
- `predict()`: accepts base64-encoded tile image, returns base64-encoded clean image + metadata
- Input/output schema defined for serving endpoint

### 3. `databricks/notebooks/register_inpainting_model.py` — Model registration notebook

- Downloads/caches YOLO + LaMa weights to UC Volume
- Logs the pyfunc model to MLflow with:
  - UC Volume weight paths as artifacts
  - Conda env with iopaint, ultralytics, torch, opencv-python
- Registers to Unity Catalog: `{catalog}.{schema}.aircraft_inpainting_model`

### 4. `resources/inpainting_serving.yml` — Serving endpoint DABs config

```yaml
resources:
  serving_endpoints:
    aircraft_inpainting:
      name: "airport-dt-aircraft-inpainting-${bundle.target}"
      config:
        served_entities:
          - entity_name: "${var.catalog}.${var.schema}.aircraft_inpainting_model"
            entity_version: 1
            workload_size: Small
            workload_type: GPU_MEDIUM  # T4
            scale_to_zero_enabled: true
```

### 5. `app/backend/api/inpainting.py` — FastAPI proxy endpoint

- `POST /api/inpainting/clean-tile` — accepts tile URL or image bytes
  - Fetches satellite tile if URL provided
  - Calls serving endpoint via Databricks SDK
  - Returns clean tile image
  - Caches results (same tile coords → same result)
- `GET /api/inpainting/status` — health check for serving endpoint

### 6. Tests

- **`tests/test_inpainting_pipeline.py`** — Unit tests for detector, inpainter, pipeline
  - Mock YOLO/LaMa for fast tests
  - Test: no detections → passthrough
  - Test: detections → mask generation → inpainting called
  - Test: base64 encoding/decoding round-trip

## Dependencies to Add

In `pyproject.toml`:
```
iopaint>=1.4
ultralytics>=8.0
opencv-python-headless>=4.8
```

## Integration with Frontend

The `SatelliteGround.tsx` component currently fetches tiles from Esri directly. After this is deployed, we can add an option to route tiles through the inpainting proxy:

```
Esri tile URL → /api/inpainting/clean-tile?url=... → clean tile
```

This is a follow-up — the serving endpoint and backend proxy work standalone first.

## Verification

1. Unit tests: `uv run pytest tests/test_inpainting_pipeline.py -v`
2. Local pipeline test: Run pipeline on a sample satellite tile, visually verify aircraft removed
3. Notebook: Run `register_inpainting_model.py` on Databricks to register model
4. Deploy: `databricks bundle deploy --target dev` to create serving endpoint
5. E2E: Call `/api/inpainting/clean-tile` with a tile URL containing visible aircraft, verify clean output

## Sequence

1. Core module (`src/ml/inpainting/`) + tests
2. MLflow pyfunc serving wrapper
3. Registration notebook + UC Volume weight caching
4. DABs serving endpoint config
5. FastAPI proxy endpoint
6. (Future) Frontend integration in `SatelliteGround.tsx`
