# Fix: Replace COCO YOLO with DOTA-trained OBB model for satellite aircraft detection

## Context

The inpainting pipeline is end-to-end operational (model registered, serving endpoint READY, test script working) but zero aircraft are detected because yolov8n.pt is trained on COCO (ground-level side-view photos). Satellite imagery at zoom 17 shows aircraft from directly above — a completely different appearance that COCO's "airplane" class cannot recognize.

## Solution

Replace yolov8n.pt (COCO) with yolov8s-obb.pt (DOTA dataset — aerial/satellite overhead imagery). DOTA class 0 = "plane" from overhead view. The OBB (Oriented Bounding Box) model returns rotated bounding boxes, which better fit aircraft shapes on satellite tiles.

## Changes

### 1. `databricks/notebooks/register_inpainting_model.py`

**Weight download section (~line 90):**
- Add download of yolov8s-obb.pt from https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8s-obb.pt
- Include it as an artifact alongside LaMa weights

**Config artifact (~line 140):**
- Change `"yolo_weights"` from `"yolov8n.pt"` to the local path of the OBB weights
- Change `"confidence_threshold"` from `0.5` to `0.3` (aerial detections may have lower confidence)

**load_context (~line 203):**
- `self._yolo_weights` now points to the OBB model artifact

**predict detection loop (~line 258-283):**
- OBB results use `r.obb` instead of `r.boxes`
- OBB provides `r.obb.xyxyxyxy` (4 corner points) instead of `r.boxes.xyxy` (2 corner points)
- Class filtering: check for class 0 (DOTA "plane") or name containing "plane"
- Mask generation: use `cv2.fillPoly` with the 4 OBB corners instead of axis-aligned rectangle
- Still apply dilation to the mask

### 2. `scripts/create_inpainting_endpoint.py`

No changes needed (endpoint config stays the same).

### 3. `scripts/test_inpainting_endpoint.py`

No changes needed (test script is model-agnostic).

## Key code change — predict method detection loop

Replace the current `r.boxes` loop with OBB-aware loop:

```python
for r in yolo_results:
    if r.obb is None:
        continue
    for i in range(len(r.obb)):
        cls_id = int(r.obb.cls[i].item())
        cls_name = r.names.get(cls_id, "")
        is_aircraft = (
            cls_id == 0  # DOTA "plane"
            or "plane" in cls_name.lower()
            or "aircraft" in cls_name.lower()
        )
        if not is_aircraft:
            continue
        conf = float(r.obb.conf[i].item())
        # OBB: 4 corner points as (x,y) pairs
        corners = r.obb.xyxyxyxy[i].cpu().numpy().astype(int)
        d = self._dilation
        # Expand corners outward by dilation
        center = corners.mean(axis=0)
        expanded = center + (corners - center) * (1 + d / 50.0)
        expanded = expanded.astype(int)
        cv2.fillPoly(mask, [expanded], 255)
        x1, y1 = corners.min(axis=0)
        x2, y2 = corners.max(axis=0)
        detections.append({
            "x1": int(x1), "y1": int(y1),
            "x2": int(x2), "y2": int(y2),
            "confidence": round(conf, 3),
            "class_name": cls_name or "plane",
        })
```

## Verification

1. Deploy bundle: `databricks bundle deploy --target dev`
2. Run registration job: `databricks bundle run inpainting_model_registration --target dev`
3. Update endpoint to new model version
4. Run test: `uv run python scripts/test_inpainting_endpoint.py --direct --airports 3 --zoom 17`
5. Compare before/after images — aircraft should be removed in "after" tiles
