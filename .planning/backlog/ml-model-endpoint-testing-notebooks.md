---
status: backlog
area: ml
related: []
---

# Plan: ML Model Endpoint Testing Notebooks

## Context

Create a Jupyter notebook for each ML model/endpoint in the Airport Digital Twin project. Each notebook serves as interactive documentation + test harness that can be run on Databricks or locally. The user wants:
1. Inpainting notebook — airport selector, satellite image display, endpoint call, result display
2. One notebook per ML model — parameter docs, endpoint call, prediction display

## Notebooks to Create

### 1. `notebooks/test_inpainting_endpoint.ipynb`

Cells:

1. **Markdown: Title + Overview** — Model description (YOLO + LaMa), architecture diagram, endpoint info
2. **Code: Setup + Auth** — imports, Databricks auth (databricks-sdk), constants (DATABRICKS_HOST, ENDPOINT_NAME)
3. **Markdown: Parameters** — table documenting endpoint input/output format
4. **Code: Airport Selector** — dropdown widget (ipywidgets) with curated airports from TERMINAL_COORDS dict in `scripts/test_inpainting_endpoint.py` (ATL, FRA, HKG, JFK, LAX, LHR, NRT, ORD, SFO). Selecting an airport displays its lat/lon and tile coordinates at zoom 17
5. **Code: Fetch & Display Satellite Tile** — fetch Esri tile at `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}`, display as PIL Image with title showing airport + coords
6. **Markdown: Endpoint Call Documentation** — payload format (dataframe_split), auth headers, response parsing
7. **Code: Call Inpainting Endpoint** — send base64-encoded tile to `https://{HOST}/serving-endpoints/{ENDPOINT}/invocations`, parse response (clean_image_b64, aircraft_count, detections), print timing + detection count
8. **Code: Display Results** — side-by-side before/after images using matplotlib (2 subplots), overlay detection bounding boxes on the original, print detections JSON

### 2. `notebooks/test_delay_prediction.ipynb`

Cells:
1. **Markdown: Title + Overview** — delay prediction model docs, rule-based heuristics description
2. **Code: Setup** — imports, base URL config, auth
3. **Markdown: Parameters** — request/response schema table (from DelaysListResponse, DelayPredictionResponse)
4. **Code: Airport Selector + Call Endpoint** — select airport, call `GET {BASE_URL}/api/predictions/delays`, optionally filter by icao24
5. **Code: Display Results** — table of delay predictions (icao24, delay_minutes, confidence, category), histogram of delay distribution, pie chart of category breakdown

### 3. `notebooks/test_gate_recommendation.ipynb`

Cells:
1. **Markdown: Title + Overview** — gate recommendation model docs, scoring algorithm
2. **Code: Setup** — imports, config, auth
3. **Markdown: Parameters** — request/response schema (path param icao24, query top_k, response GateRecommendationResponse)
4. **Code: Flight Selector + Call Endpoint** — list active flights via `/api/flights`, select one, call `GET {BASE_URL}/api/predictions/gates/{icao24}?top_k=3`
5. **Code: Display Results** — table of recommendations (gate_id, score, reasons, taxi_time), bar chart of scores

### 4. `notebooks/test_congestion_prediction.ipynb`

Cells:
1. **Markdown: Title + Overview** — congestion model docs, area definitions, capacity thresholds
2. **Code: Setup** — imports, config, auth
3. **Markdown: Parameters** — request/response schema (CongestionListResponse, CongestionSummaryResponse)
4. **Code: Call Congestion + Bottleneck Endpoints** — `GET /api/predictions/congestion` and `GET /api/predictions/bottlenecks`
5. **Code: Display Results** — table of all areas (area_id, type, level, flight_count, capacity, wait), color-coded by level (green/yellow/orange/red), separate bottleneck highlight

## Key Implementation Details

### Authentication

```python
# Works in both Databricks notebooks and local Jupyter
try:
    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()
    token = w.config.authenticate()["Authorization"].removeprefix("Bearer ")
except Exception:
    import subprocess, json
    result = subprocess.run(
        ["databricks", "auth", "token", "--profile", "FEVM_SERVERLESS_STABLE"],
        capture_output=True, text=True, timeout=15
    )
    token = json.loads(result.stdout)["access_token"]
```

### Constants

- `APP_BASE_URL = "https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com"`
- `DATABRICKS_HOST = "fevm-serverless-stable-3n0ihb.cloud.databricks.com"`
- `INPAINTING_ENDPOINT = "airport-dt-aircraft-inpainting-dev"`
- `ESRI_TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"`

### Airport Selector (Inpainting)

Uses curated TERMINAL_COORDS dict from `scripts/test_inpainting_endpoint.py`:
```python
TERMINAL_COORDS = {
    "ATL": (33.6407, -84.4277), "FRA": (50.0500, 8.5700),
    "HKG": (22.3107, 113.9159), "JFK": (40.6413, -73.7781),
    "LAX": (33.9422, -118.4093), "LHR": (51.4703, -0.4601),
    "NRT": (35.7721, 140.3929), "ORD": (41.9742, -87.9073),
    "SFO": (37.6197, -122.3836),
}
```

### Tile Coordinate Conversion

```python
def lat_lon_to_tile(lat, lon, zoom):
    import math
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_rad) + 1/math.cos(lat_rad)) / math.pi) / 2 * n)
    return x, y
```

### Inpainting Endpoint Payload

```python
payload = {
    "dataframe_split": {
        "columns": ["image_b64"],
        "data": [[base64.b64encode(image_bytes).decode()]]
    }
}
# POST to https://{HOST}/serving-endpoints/{ENDPOINT}/invocations
# Response: predictions[0] = [clean_image_b64, aircraft_count, detections_json]
```

### Prediction Endpoints (via App Proxy)

All use the app base URL with Bearer auth:
- `GET /api/predictions/delays?icao24={optional}`
- `GET /api/predictions/gates/{icao24}?top_k=3`
- `GET /api/predictions/congestion`
- `GET /api/predictions/bottlenecks`
- `GET /api/predictions/congestion-summary`

## Files Created

| File | Description |
|------|-------------|
| `notebooks/test_inpainting_endpoint.ipynb` | Inpainting model: airport selector, satellite display, endpoint call, before/after comparison |
| `notebooks/test_delay_prediction.ipynb` | Delay model: parameter docs, endpoint call, delay distribution charts |
| `notebooks/test_gate_recommendation.ipynb` | Gate model: flight selector, endpoint call, recommendation table + chart |
| `notebooks/test_congestion_prediction.ipynb` | Congestion model: endpoint calls, area table, color-coded levels |

## Verification

1. Open each notebook in Jupyter / Databricks
2. Run all cells — auth should succeed, endpoints should return data
3. Inpainting: satellite tile displays, endpoint call returns clean image, side-by-side comparison renders
4. Predictions: tables and charts render with live data from the deployed app
