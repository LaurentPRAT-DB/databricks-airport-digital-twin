# Inpainting Service Validation Report — PROD

**Date:** 2026-05-28  
**App:** https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com  
**Endpoint:** `airport-dt-aircraft-inpainting-dev` (YOLO + LaMa on Model Serving)

---

## Executive Summary

The inpainting service **works well for high-confidence detections** but has significant **recall gaps** — it misses ~50% of visible aircraft per tile. When it does detect, cleanup is 100% effective with no false positives.

| Metric | Value | Rating |
|--------|-------|--------|
| Total tiles validated | 68 | — |
| Tiles with aircraft detected | 22 (32.4%) | — |
| Successful cleanup rate | **100%** (22/22) | Excellent |
| False positive rate | **0.0%** | Excellent |
| Region cleanup effectiveness | **100%** (61/61 bboxes) | Excellent |
| Avg pixel change in detection regions | 90.3% | Excellent |
| Airports with cache | 1 (KSFO only) | Poor coverage |

## Key Findings

### What Works Well
- **Zero false positives** — no tiles corrupted without reason
- **100% cleanup success** — every detected aircraft is effectively removed
- **High region accuracy** — 90.3% average pixel change within detection bounding boxes
- **Cache system works** — ETag-based freshness, proper HIT/STALE/MISS logic
- **No artifacts on clean tiles** — tiles without aircraft are returned byte-identical

### What Needs Improvement
- **Low recall** — visual inspection shows ~50% of aircraft missed per tile
  - z16/10487/25366: 7 detected, but ~12 visible in original → 5 missed
  - z17/20976/50733: 3 detected, but ~7 visible → 4 missed
  - Missed aircraft tend to be: partially under jetbridges, at unusual angles, or smaller regional jets
- **Only 1 airport cached** — KSFO has 68 tiles; cache reports 2 airports/149 tiles total but 81 tiles unreachable via scan (possibly different ICAO tagging or older zoom levels)
- **Inpainting texture quality at z17** — fill texture appears washed-out/pale compared to actual tarmac. Acceptable at z16.
- **No coverage beyond KSFO** — no other airports pre-warmed

## Detection Quality Deep-Dive

### Per-Tile Aircraft Count vs Visible Reality (visual inspection)

| Tile | Detected | Actually Visible | Miss Rate |
|------|----------|-----------------|-----------|
| z16/10488/25366 | 16 | ~20 | ~20% |
| z16/10487/25366 | 7 | ~12 | ~42% |
| z17/20976/50733 | 3 | ~7 | ~57% |
| z17/20978/50734 | 3 | ~12 | ~75% |

Miss rate increases at z17 where aircraft are larger in pixel space but often partially occluded by jetbridges.

### Pixel Difference Statistics (tiles with detections)

- Mean L2 RGB distance: 2.05 (subtle overall, concentrated in bbox regions)
- Max L2 distance: 355 (full white→dark in aircraft removal areas)
- Avg changed pixels per tile: 4.14% (appropriate — aircraft are small relative to tile)
- Range: 0.41% to 12.49%

---

## Improvement Suggestions (Minimal Code Changes)

### 1. Lower detection confidence threshold (1-line change)

**Problem:** Threshold 0.5 misses aircraft with partial occlusion (jetbridges, shadows).  
**File:** `src/ml/inpainting/pipeline.py:38`  
**Change:** `confidence_threshold` default from `0.5` → `0.3`

```python
# Before
confidence_threshold: float = 0.5,

# After  
confidence_threshold: float = 0.3,
```

**Expected impact:** +30-40% more detections. Risk: may detect vehicles/ground equipment. Mitigate with class filtering already in place.

### 2. Increase mask dilation for cleaner edges (1-line change)

**Problem:** Tight 10px dilation leaves aircraft shadow/edge artifacts.  
**File:** `src/ml/inpainting/pipeline.py:40`  
**Change:** `mask_dilation_px` from `10` → `18`

```python
# Before
mask_dilation_px: int = 10,

# After
mask_dilation_px: int = 18,
```

**Expected impact:** Cleaner inpainting boundaries, less visible seam artifacts. Minimal extra computation.

### 3. Add NMS IoU tuning (1-line addition)

**Problem:** Overlapping detections may merge, losing some aircraft.  
**File:** `src/ml/inpainting/detector.py:80`  
**Change:** Add `iou` parameter to YOLO predict:

```python
# Before
results = self._model.predict(
    image,
    conf=self.confidence_threshold,
    device=self.device,
    verbose=False,
)

# After
results = self._model.predict(
    image,
    conf=self.confidence_threshold,
    iou=0.3,
    device=self.device,
    verbose=False,
)
```

**Expected impact:** Prevents adjacent aircraft from being merged into one detection.

### 4. Cache pre-warming job (new file + deploy.sh addition)

**Problem:** Only KSFO cached. Other airports served without inpainting.  
**Where:** Add to `deploy.sh` post-deploy, or create `resources/inpainting_warmup_job.yml`

```bash
# In deploy.sh, after app restart:
echo "Pre-warming inpainting cache..."
uv run python scripts/test_inpainting_endpoint.py --zoom 16 --concurrency 3 &
```

### 5. Multi-zoom detection for small aircraft (serving model change)

**Problem:** At z16, small regional jets are ~15px — below YOLO effective detection size.  
**File:** `src/ml/inpainting/serving.py` (model wrapper)  
**Change:** Run detection at 2x upscaled image, map bboxes back to original coords.

**Expected impact:** +20% detection of small aircraft. Cost: ~2x inference time.

---

## Test Artifacts

```
reports/inpainting_validation/
├── validation_report.json     # Full machine-readable results (68 tiles)
├── REPORT.md                  # Auto-generated markdown
└── KSFO/
    ├── z16/                   # 13 before/after pairs
    │   ├── before_10488_25366.png  (16 aircraft → all removed)
    │   └── after_10488_25366.png
    └── z17/                   # 9 before/after pairs
        ├── before_20978_50734.png  (3 detected of ~12 visible)
        └── after_20978_50734.png
```

## Recommended Priority Order

| # | Change | Effort | Impact | Risk |
|---|--------|--------|--------|------|
| 1 | Lower threshold to 0.3 | 1 line | +30-40% recall | Low (0% FP currently) |
| 2 | Increase dilation to 18px | 1 line | Better visual quality | None |
| 3 | Add IoU=0.3 | 1 line | Fixes merged detections | None |
| 4 | Cache pre-warming job | New file | All airports covered | None |
| 5 | Multi-zoom detection | ~20 lines | +20% small aircraft | 2x latency |
