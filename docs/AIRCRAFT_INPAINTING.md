# Aircraft Inpainting — Satellite Tile Cleanup

Remove real-world aircraft from satellite imagery so the 3D view shows only simulated traffic. Uses oriented object detection (YOLOv8s-OBB trained on DOTA satellite data) to locate aircraft, then LaMa neural inpainting to fill the masked regions with surrounding tarmac/apron texture.

## Architecture

```
Esri Satellite Tile (256x256 PNG)
        │
        ▼
┌───────────────────────────────────┐
│  Databricks Model Serving         │
│  (GPU_MEDIUM, scale-to-zero)      │
│                                   │
│  1. YOLOv8s-OBB (DOTA)           │  ← Detects aircraft with oriented bounding boxes
│     conf ≥ 0.15, class "plane"    │
│                                   │
│  2. Mask generation               │  ← OBB polygons dilated outward for clean edges
│     cv2.fillPoly + scale factor   │
│                                   │
│  3. LaMa inpainting              │  ← Fills masked regions with surrounding texture
│     simple-lama-inpainting        │
│     (fallback: IOPaint → OpenCV)  │
└───────────────────────────────────┘
        │
        ▼
Clean tile (256x256 PNG, aircraft removed)
        │
        ▼
┌───────────────────────────┐
│ Lakebase Tile Cache       │  ← PostgreSQL cache keyed by z/x/y + source ETag
│ satellite_tile_cache      │     Auto-invalidates when Esri updates imagery
└───────────────────────────┘
```

## Models

### Detection: YOLOv8s-OBB

- **Weights:** `yolov8s-obb.pt` (Ultralytics, trained on DOTA satellite dataset)
- **Task:** Oriented Bounding Box (OBB) detection — outputs rotated rectangles, not axis-aligned boxes
- **Class:** `plane` (DOTA class 0)
- **Confidence threshold:** 0.15 (satellite aircraft appear small and low-contrast)
- **Stored in:** UC Volume at `/Volumes/{catalog}/{schema}/model_weights/yolov8s-obb.pt`

Why OBB over standard YOLO: Aircraft are oriented at arbitrary angles on satellite imagery. Axis-aligned bounding boxes would overlap with adjacent gates/jetways; oriented boxes tightly wrap each aircraft regardless of heading.

### Inpainting: LaMa (Large Mask Inpainting)

- **Weights:** `big-lama.pt` from [Sanster/models](https://github.com/Sanster/models/releases)
- **Library:** `simple-lama-inpainting` (lightweight PyTorch wrapper)
- **Fallbacks:** IOPaint ModelManager → OpenCV TELEA (if torch unavailable)
- **Stored in:** UC Volume at `/Volumes/{catalog}/{schema}/model_weights/lama/big-lama.pt`

LaMa excels at filling regular textures (concrete, asphalt, painted lines) — ideal for airport tarmac.

## Components

| Component | Path | Role |
|-----------|------|------|
| Detection | `src/ml/inpainting/detector.py` | `AircraftDetector` — YOLO wrapper, generates binary masks |
| Inpainting | `src/ml/inpainting/inpainter.py` | `LaMaInpainter` — multi-backend inpainting |
| Pipeline | `src/ml/inpainting/pipeline.py` | `InpaintingPipeline` — detect → mask → inpaint orchestration |
| Serving model | `src/ml/inpainting/serving.py` | `AircraftInpaintingModel` — MLflow pyfunc for Model Serving |
| Registration notebook | `databricks/notebooks/register_inpainting_model.py` | Downloads weights to UC Volume, registers model to UC |
| Backend API | `app/backend/api/inpainting.py` | FastAPI proxy — tile fetch, serving call, Lakebase cache |
| Frontend | `app/frontend/src/components/Map3D/SatelliteGround.tsx` | Routes satellite tiles through inpainting proxy |
| UI toggle | `app/frontend/src/App.tsx` | "Clean Tiles" button, endpoint wake/status polling |
| Tile cache | `app/backend/services/lakebase_service.py` | Lakebase PostgreSQL tile cache with ETag invalidation |
| Test script | `scripts/test_inpainting_endpoint.py` | CLI tool for batch testing across airports |

## Databricks Resources

| Resource | Config | Description |
|----------|--------|-------------|
| Serving endpoint | `resources/inpainting_serving.yml` | `airport-dt-aircraft-inpainting-{target}`, GPU_MEDIUM, scale-to-zero |
| Registration job | `resources/inpainting_registration_job.yml` | Downloads weights + registers MLflow model |
| Tile cache table | `scripts/lakebase_schema.sql` | `satellite_tile_cache` in Lakebase PostgreSQL |

## API Endpoints

All endpoints are under `/api/inpainting` (defined in `inpainting_router`).

### `POST /api/inpainting/clean-tile`

Remove aircraft from a satellite tile. Primary endpoint used by the frontend.

**Query params:**
- `url` (string) — Esri satellite tile URL to fetch and clean
- `airport_icao` (string, optional) — ICAO code for cache tagging
- `file` (upload, optional) — Direct image upload instead of URL

**Response:** PNG image (binary) with headers:
- `X-Cache: HIT` or `MISS`
- `X-Aircraft-Count: 3`
- `X-Processing-Ms: 1200`

**Cache flow:**
1. Parse tile coords from URL (`/tile/{z}/{y}/{x}`)
2. HEAD request to Esri for source ETag
3. Check Lakebase cache — return if ETag matches
4. On miss: fetch tile, call serving endpoint, cache result, return

**Example (curl):**
```bash
TOKEN=$(databricks auth token --profile FEVM_SERVERLESS_STABLE | jq -r .access_token)

curl -X POST \
  "https://airport-digital-twin-dev-*.aws.databricksapps.com/api/inpainting/clean-tile?url=https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/17/49314/38674&airport_icao=KJFK" \
  -H "Authorization: Bearer $TOKEN" \
  --output cleaned_tile.png
```

### `GET /api/inpainting/status`

Health check for the serving endpoint and cache stats.

**Response:**
```json
{
  "status": "ok",
  "endpoint": "airport-dt-aircraft-inpainting-dev",
  "ready": "READY",
  "cache": {
    "total_tiles": 42,
    "total_aircraft_removed": 87,
    "airports_covered": 9,
    "avg_processing_ms": 1200
  }
}
```

### `POST /api/inpainting/wake`

Trigger scale-up of a cold (scale-to-zero) endpoint. Sends a 1x1 PNG to trigger the wake without blocking.

**Response:**
```json
{"status": "waking", "message": "Wake-up request sent. Endpoint is scaling up (may take 2-5 minutes)."}
```

### `GET /api/inpainting/cache-stats`

Return tile cache statistics from Lakebase.

## Calling the Serving Endpoint Directly

Bypass the app proxy and call the Databricks serving endpoint with a base64-encoded image.

```python
import base64, httpx, json

TOKEN = "dapi..."
HOST = "fevm-serverless-stable-3n0ihb.cloud.databricks.com"
ENDPOINT = "airport-dt-aircraft-inpainting-dev"

# Read a satellite tile
with open("tile.png", "rb") as f:
    image_b64 = base64.b64encode(f.read()).decode()

# Call the serving endpoint
resp = httpx.post(
    f"https://{HOST}/serving-endpoints/{ENDPOINT}/invocations",
    json={"dataframe_split": {"columns": ["image_b64"], "data": [[image_b64]]}},
    headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    timeout=120,
)

result = resp.json()
predictions = result["predictions"]
if isinstance(predictions, dict):
    data = predictions["data"][0]
    clean_b64, aircraft_count, detections = data[0], data[1], data[2]
else:
    pred = predictions[0]
    clean_b64 = pred["clean_image_b64"]
    aircraft_count = pred["aircraft_count"]
    detections = pred["detections"]

print(f"Detected {aircraft_count} aircraft")

# Save cleaned tile
with open("tile_clean.png", "wb") as f:
    f.write(base64.b64decode(clean_b64))
```

## Frontend Usage

In the 3D view:

1. Enable **Satellite** imagery toggle (loads Esri World Imagery tiles)
2. Click the **Clean Tiles** button (sparkles icon)
3. If the endpoint is scaled to zero, a banner appears — click **Start Endpoint** and wait 2-5 min
4. Once ready, satellite tiles automatically route through `/api/inpainting/clean-tile`
5. Cleaned tiles replace originals on the 3D ground plane

The `SatelliteGround` component accepts `inpainting` and `airportIcao` props:

```tsx
<SatelliteGround
  size={4000}
  centerLat={40.6413}
  centerLon={-73.7781}
  satellite={true}
  inpainting={true}           // Route tiles through inpainting proxy
  airportIcao="KJFK"          // Cache tag for Lakebase
/>
```

## Batch Testing

Test inpainting across multiple airports using the CLI script:

```bash
# Test all 9 curated airports (terminal coordinates with known aircraft)
uv run python scripts/test_inpainting_endpoint.py --direct --zoom 17

# Test via app proxy instead of direct
uv run python scripts/test_inpainting_endpoint.py --zoom 17

# Limit to 3 airports with custom concurrency
uv run python scripts/test_inpainting_endpoint.py --direct --airports 3 --concurrency 1

# Use all airports from AIRPORTS table (not just curated)
uv run python scripts/test_inpainting_endpoint.py --direct --all --zoom 16
```

Output goes to `reports/inpainting/`:
- `{ICAO}/before_{z}_{x}_{y}.png` — original Esri tile
- `{ICAO}/after_{z}_{x}_{y}.png` — inpainted tile
- `{ICAO}_comparison.png` — side-by-side composite
- `overview_grid.png` — grid of all airports
- `results.json` — raw results
- `report.md` — markdown summary

## Test Results (2026-03-30)

Model v4: YOLOv8s-OBB + simple-lama-inpainting, confidence=0.15

| Airport | Aircraft Detected | Latency |
|---------|------------------|---------|
| EDDF (Frankfurt) | 5 | 168s* |
| EGLL (Heathrow) | 1 | 5s |
| KATL (Atlanta) | 4 | 167s* |
| KJFK (JFK) | 7 | 5s |
| KLAX (LAX) | 3 | 165s* |
| KORD (O'Hare) | 2 | 5s |
| KSFO (SFO) | 8 | 166s* |
| RJAA (Narita) | 1 | 163s* |
| VHHH (Hong Kong) | 3 | 5s |
| **Total** | **34** | |

*High latency = cold start (scale-to-zero wake-up). Warm latency is ~1-5s per tile.

## Deployment

### Register/update the model

```bash
# Deploy notebook to workspace
databricks bundle deploy --target dev

# Run the registration job (downloads weights, registers MLflow model)
databricks bundle run inpainting_model_registration --target dev
```

### Update the serving endpoint version

```bash
# Check current model versions
databricks unity-catalog models list-versions \
  --full-name serverless_stable_3n0ihb_catalog.airport_digital_twin.aircraft_inpainting_model

# Update endpoint to latest version (e.g., v4)
curl -X PUT \
  "https://$HOST/api/2.0/serving-endpoints/airport-dt-aircraft-inpainting-dev/config" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "served_entities": [{
      "entity_name": "serverless_stable_3n0ihb_catalog.airport_digital_twin.aircraft_inpainting_model",
      "entity_version": "4",
      "workload_size": "Small",
      "workload_type": "GPU_MEDIUM",
      "scale_to_zero_enabled": true
    }]
  }'
```

### Lakebase tile cache

The `satellite_tile_cache` table is created automatically by the backend on first use. To create it manually:

```sql
-- See scripts/lakebase_schema.sql for full DDL
CREATE TABLE IF NOT EXISTS satellite_tile_cache (
    tile_key VARCHAR(100) PRIMARY KEY,
    zoom INTEGER NOT NULL,
    tile_x INTEGER NOT NULL,
    tile_y INTEGER NOT NULL,
    airport_icao VARCHAR(4),
    original_etag VARCHAR(200),
    inpainted_image BYTEA NOT NULL,
    aircraft_count INTEGER NOT NULL DEFAULT 0,
    detections_json JSONB,
    processing_time_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

## Configuration

Key parameters in the model config (`databricks/notebooks/register_inpainting_model.py`):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `confidence_threshold` | 0.15 | YOLO detection confidence. Lower = more detections, more false positives |
| `mask_dilation_px` | 10 | Pixels to expand each detection mask for cleaner inpainting edges |
| `device` | auto | `cuda` on GPU endpoints, `cpu` fallback |
| `yolo_weights` | UC Volume path | Path to YOLOv8s-OBB weights |
| `lama_weights_file` | UC Volume path | Path to big-lama.pt checkpoint |

Environment variables for the backend proxy (`app.yaml`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABRICKS_HOST` | (from app platform) | Workspace URL for serving endpoint calls |
| `INPAINTING_ENDPOINT_NAME` | `airport-dt-aircraft-inpainting-dev` | Serving endpoint name |
