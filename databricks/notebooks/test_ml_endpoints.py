# Databricks notebook source
# MAGIC %md
# MAGIC # ML Model Endpoint Validation
# MAGIC
# MAGIC **Purpose:** Validate all four ML model endpoints deployed in the Airport Digital Twin, with realistic data and visual output so the results can be reviewed after execution.
# MAGIC
# MAGIC ---
# MAGIC
# MAGIC ### Who is this for?
# MAGIC
# MAGIC | Audience | What to look for |
# MAGIC |----------|-----------------|
# MAGIC | **Airport Operations** | Does each prediction make operational sense? Are delay estimates realistic? Are gate assignments plausible? Does the congestion map match expected traffic patterns? Does satellite cleanup remove aircraft without introducing visual artifacts? |
# MAGIC | **Data Science / ML Engineering** | Are confidence scores well-calibrated? Is the delay distribution reasonable? Are detection bounding boxes tight? What's the endpoint latency? Are there any silent failures? |
# MAGIC
# MAGIC ### Models Tested
# MAGIC
# MAGIC | # | Model | Endpoint | What it predicts |
# MAGIC |---|-------|----------|------------------|
# MAGIC | 1 | **Aircraft Inpainting** | Databricks Model Serving (GPU) | Detects and removes real aircraft from satellite tiles so the 3D view shows only simulated traffic |
# MAGIC | 2 | **Delay Prediction** | App API `/api/predictions/delays` | Estimated arrival/departure delay per flight based on time-of-day, altitude, speed, and congestion |
# MAGIC | 3 | **Gate Recommendation** | App API `/api/predictions/gates/{icao24}` | Optimal gate assignment considering availability, terminal type, taxi distance, and delay impact |
# MAGIC | 4 | **Congestion Prediction** | App API `/api/predictions/congestion-summary` | Real-time utilization of runways, taxiways, and aprons with wait-time estimates |

# COMMAND ----------

%pip install httpx matplotlib pillow --quiet

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# ── Setup & Authentication ──────────────────────────────────────────────────

import io
import json
import math
import time
from datetime import datetime, timezone

import httpx
import matplotlib
matplotlib.use("Agg")   # headless backend for serverless
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from PIL import Image

# Widgets — set by the job, or editable when running manually
dbutils.widgets.text("app_url",
    "https://airport-digital-twin-dev-7474645572615955.aws.databricksapps.com",
    "App Base URL")
dbutils.widgets.text("airport_iata", "SFO", "Airport IATA (inpainting tile)")

APP_URL = dbutils.widgets.get("app_url").rstrip("/")
AIRPORT_IATA = dbutils.widgets.get("airport_iata").upper()

# Auth: the Databricks Apps proxy requires a Bearer token. We use the notebook
# context token which has the right scope for both app proxy and serving endpoints.
TOKEN = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

# Collect results for final summary
results = {}

print(f"App URL:    {APP_URL}")
print(f"Airport:    {AIRPORT_IATA}")
print(f"Auth:       notebook context token ({len(TOKEN)} chars)")
print(f"Timestamp:  {datetime.now(timezone.utc).isoformat()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC # Model 1 — Aircraft Inpainting (YOLO + LaMa)
# MAGIC
# MAGIC ## What does this do?
# MAGIC
# MAGIC **For airport operators:** Real-world satellite imagery shows parked aircraft at gates. When the digital twin
# MAGIC overlays simulated flights on this imagery, the real and simulated aircraft overlap — confusing the view.
# MAGIC This model **detects real aircraft in satellite tiles and erases them**, filling the gaps with surrounding
# MAGIC tarmac texture. The result is a clean aerial view that only shows the twin's simulated traffic.
# MAGIC
# MAGIC **For data scientists:** Two-stage deep learning pipeline served on Databricks Model Serving (GPU_MEDIUM, scale-to-zero):
# MAGIC
# MAGIC 1. **Detection** — YOLOv8s-OBB (trained on DOTA satellite dataset) detects aircraft using **oriented bounding boxes**
# MAGIC    (rotated rectangles, not axis-aligned) at confidence threshold 0.15. OBB is critical because aircraft sit at
# MAGIC    arbitrary angles on the apron; axis-aligned boxes would overlap jetways and adjacent gates.
# MAGIC
# MAGIC 2. **Inpainting** — LaMa (Large Mask Inpainting) fills each detected region with surrounding texture.
# MAGIC    LaMa excels at regular textures like concrete, asphalt, and painted taxiway lines — ideal for airport tarmac.
# MAGIC
# MAGIC ```
# MAGIC Esri Satellite Tile (256x256 PNG)
# MAGIC      |
# MAGIC      v
# MAGIC  YOLOv8s-OBB  -->  Oriented BBoxes  -->  Binary Mask (dilated 10px)
# MAGIC      |                                          |
# MAGIC      v                                          v
# MAGIC  LaMa Inpainter  <------------------------------+
# MAGIC      |
# MAGIC      v
# MAGIC  Clean Tile (aircraft removed)
# MAGIC ```
# MAGIC
# MAGIC ### Endpoint Input/Output
# MAGIC
# MAGIC | Direction | Field | Type | Description |
# MAGIC |-----------|-------|------|-------------|
# MAGIC | **Input** | `image_b64` | string | Base64-encoded satellite tile (PNG/JPEG, typically 256x256 px) |
# MAGIC | **Output** | `clean_image_b64` | string | Base64-encoded inpainted PNG |
# MAGIC | **Output** | `aircraft_count` | int | Number of aircraft detected and removed |
# MAGIC | **Output** | `detections` | JSON string | Bounding boxes: `[{"x1", "y1", "x2", "y2", "confidence", "class_name"}]` |
# MAGIC
# MAGIC ### Key Configuration
# MAGIC
# MAGIC | Parameter | Value | Effect |
# MAGIC |-----------|-------|--------|
# MAGIC | `confidence_threshold` | 0.15 | Lower catches faint/small aircraft but risks false positives on ground vehicles |
# MAGIC | `mask_dilation_px` | 10 | Expands each detection mask by 10px for cleaner inpainting at aircraft edges |
# MAGIC | Scale-to-zero | Enabled | Endpoint sleeps after inactivity — first call takes 2-5 min for GPU cold start |

# COMMAND ----------

# ── Inpainting: Select Airport & Fetch Satellite Tile ────────────────────────

# Curated terminal coordinates where Esri World Imagery shows parked aircraft.
# Each position was verified visually at zoom 17.
TERMINAL_COORDS = {
    "ATL": (33.6407, -84.4277,  "KATL", "Concourse T — Hartsfield-Jackson Atlanta"),
    "FRA": (50.0500,   8.5700,  "EDDF", "Terminal 1 — Frankfurt am Main"),
    "HKG": (22.3107, 113.9159,  "VHHH", "Terminal 1 — Hong Kong International"),
    "JFK": (40.6413, -73.7781,  "KJFK", "Terminal 4 — John F. Kennedy"),
    "LAX": (33.9422, -118.4093, "KLAX", "Tom Bradley International Terminal"),
    "LHR": (51.4703,  -0.4601,  "EGLL", "Terminal 5 — London Heathrow"),
    "NRT": (35.7721, 140.3929,  "RJAA", "Terminal 1 Apron — Narita"),
    "ORD": (41.9742, -87.9073,  "KORD", "Terminal 5 — Chicago O'Hare"),
    "SFO": (37.6197, -122.3836, "KSFO", "International Terminal — San Francisco"),
}

ESRI_TILE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
ZOOM = 17


def lat_lon_to_tile(lat, lon, zoom):
    """Convert geographic coordinates to Slippy Map tile indices."""
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * n)
    return x, y


# Resolve selected airport
if AIRPORT_IATA not in TERMINAL_COORDS:
    print(f"Airport {AIRPORT_IATA} not in curated list, falling back to SFO")
    AIRPORT_IATA_RESOLVED = "SFO"
else:
    AIRPORT_IATA_RESOLVED = AIRPORT_IATA

lat, lon, icao, description = TERMINAL_COORDS[AIRPORT_IATA_RESOLVED]
tile_x, tile_y = lat_lon_to_tile(lat, lon, ZOOM)
tile_url = ESRI_TILE_URL.format(z=ZOOM, y=tile_y, x=tile_x)

print(f"Airport:     {AIRPORT_IATA_RESOLVED} ({icao})")
print(f"Location:    {description}")
print(f"Coordinates: {lat:.4f}N, {lon:.4f}E")
print(f"Tile:        zoom={ZOOM}, x={tile_x}, y={tile_y}")
print(f"Tile URL:    {tile_url}")

# Fetch the satellite tile
resp = httpx.get(tile_url, timeout=30)
resp.raise_for_status()
original_bytes = resp.content
original_image = Image.open(io.BytesIO(original_bytes))

fig, ax = plt.subplots(1, 1, figsize=(6, 6))
ax.imshow(original_image)
ax.set_title(
    f"Esri World Imagery — {AIRPORT_IATA_RESOLVED} ({icao})\n"
    f"{description}\nTile {ZOOM}/{tile_x}/{tile_y} | {len(original_bytes):,} bytes",
    fontsize=10,
)
ax.axis("off")
plt.tight_layout()
plt.show()

# COMMAND ----------

# ── Inpainting: Call App Endpoint ────────────────────────────────────────────
#
# Calls the app's /api/inpainting/clean-tile endpoint, which handles the full
# pipeline: fetch tile → call serving endpoint → cache result.
#
# The response is the cleaned PNG image with metadata in response headers:
#   X-Aircraft-Count: number of aircraft detected and removed
#   X-Detections: JSON array of bounding boxes [{x1, y1, x2, y2, confidence, class_name}]
#   X-Cache: HIT or MISS
#   X-Processing-Ms: serving endpoint latency (on cache miss)
#
# Note: if the serving endpoint is scaled to zero, this call may take 2-5 min
# on the first invocation while the GPU instance cold-starts.

inpainting_url = f"{APP_URL}/api/inpainting/clean-tile?url={tile_url}&airport_icao={icao}"
print(f"POST {inpainting_url}")

t0 = time.monotonic()
try:
    resp = httpx.post(inpainting_url, headers=HEADERS, timeout=300)
    inpainting_latency_ms = int((time.monotonic() - t0) * 1000)

    if resp.status_code != 200:
        print(f"FAIL: HTTP {resp.status_code} ({inpainting_latency_ms}ms)")
        print(resp.text[:500])
        results["inpainting"] = {"status": "FAIL", "error": f"HTTP {resp.status_code}", "latency_ms": inpainting_latency_ms}
        clean_bytes = None
        detections = []
        aircraft_count = 0
    else:
        clean_bytes = resp.content
        aircraft_count = int(resp.headers.get("X-Aircraft-Count", 0))
        detections_raw = resp.headers.get("X-Detections", "[]")
        detections = json.loads(detections_raw) if isinstance(detections_raw, str) else (detections_raw or [])
        cache_status = resp.headers.get("X-Cache", "?")

        print(f"OK: {resp.status_code} ({inpainting_latency_ms}ms) [cache: {cache_status}]")
        print(f"Aircraft detected: {aircraft_count}")
        print(f"Clean tile size:   {len(clean_bytes):,} bytes")
        results["inpainting"] = {
            "status": "PASS",
            "aircraft_count": aircraft_count,
            "latency_ms": inpainting_latency_ms,
            "detections": len(detections),
        }

except Exception as e:
    inpainting_latency_ms = int((time.monotonic() - t0) * 1000)
    print(f"FAIL: {e} ({inpainting_latency_ms}ms)")
    results["inpainting"] = {"status": "FAIL", "error": str(e), "latency_ms": inpainting_latency_ms}
    clean_bytes = None
    detections = []
    aircraft_count = 0

# COMMAND ----------

# ── Inpainting: Visual Comparison (Before / After / Diff) ────────────────────
#
# Three large panels for human review:
#   1. BEFORE  — original satellite tile with red detection boxes
#   2. AFTER   — inpainted tile (aircraft removed)
#   3. DIFF    — pixel difference heatmap highlighting exactly what changed
#
# Then: zoomed crops around each detected aircraft so a reviewer can judge
# inpainting quality at pixel level (texture continuity, edge artifacts).
#
# What to look for:
#   - Ops:  are the red boxes around actual aircraft (not vehicles/shadows)?
#           Does the cleaned tile look natural — no smearing, no missing taxiway lines?
#   - ML:   are confidence scores > 0.3 for clearly visible aircraft?
#           Is the diff confined to aircraft regions or bleeding into surroundings?

import numpy as np

if clean_bytes:
    clean_image = Image.open(io.BytesIO(clean_bytes))

    # ── Panel 1: Before / After / Diff (full tile, large) ────────────────
    orig_arr = np.array(original_image.convert("RGB"))
    clean_arr = np.array(clean_image.convert("RGB"))
    # Absolute pixel difference — amplified for visibility
    diff_arr = np.abs(orig_arr.astype(int) - clean_arr.astype(int)).astype(np.uint8)
    diff_amplified = np.clip(diff_arr * 4, 0, 255).astype(np.uint8)

    fig, axes = plt.subplots(1, 3, figsize=(20, 8), dpi=150)

    # BEFORE with detection boxes
    axes[0].imshow(original_image, interpolation="nearest")
    axes[0].set_title(f"BEFORE — {aircraft_count} aircraft detected", fontsize=12, fontweight="bold")
    for det in detections:
        x1, y1 = det["x1"], det["y1"]
        x2, y2 = det["x2"], det["y2"]
        conf = det.get("confidence", 0)
        rect = matplotlib.patches.Rectangle(
            (x1, y1), x2 - x1, y2 - y1,
            linewidth=2, edgecolor="red", facecolor="none",
        )
        axes[0].add_patch(rect)
        axes[0].text(
            x1, max(0, y1 - 4), f"{conf:.2f}",
            color="white", fontsize=7, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.15", facecolor="red", alpha=0.85),
        )
    axes[0].axis("off")

    # AFTER
    axes[1].imshow(clean_image, interpolation="nearest")
    axes[1].set_title(f"AFTER — aircraft removed ({inpainting_latency_ms:,}ms)", fontsize=12, fontweight="bold")
    axes[1].axis("off")

    # DIFF heatmap
    axes[2].imshow(diff_amplified, interpolation="nearest")
    axes[2].set_title("DIFFERENCE (4x amplified)", fontsize=12, fontweight="bold")
    axes[2].axis("off")

    plt.suptitle(
        f"Aircraft Inpainting: {AIRPORT_IATA_RESOLVED} ({icao}) — {description}",
        fontsize=13, fontweight="bold",
    )
    plt.tight_layout()
    plt.show()

    # ── Panel 2: Zoomed crops around each detection ──────────────────────
    # Shows before/after side by side for each detected aircraft so a human
    # reviewer can judge inpainting quality at the pixel level.
    if detections:
        PAD = 20  # extra pixels around each detection for context
        n_det = min(len(detections), 8)  # cap at 8 to avoid huge output
        fig, axes = plt.subplots(n_det, 3, figsize=(15, 4 * n_det), dpi=150)
        if n_det == 1:
            axes = axes[np.newaxis, :]  # ensure 2D indexing

        for i, det in enumerate(detections[:n_det]):
            x1 = max(0, int(det["x1"]) - PAD)
            y1 = max(0, int(det["y1"]) - PAD)
            x2 = min(orig_arr.shape[1], int(det["x2"]) + PAD)
            y2 = min(orig_arr.shape[0], int(det["y2"]) + PAD)
            conf = det.get("confidence", 0)

            crop_before = orig_arr[y1:y2, x1:x2]
            crop_after = clean_arr[y1:y2, x1:x2]
            crop_diff = diff_amplified[y1:y2, x1:x2]

            axes[i, 0].imshow(crop_before, interpolation="nearest")
            axes[i, 0].set_title(f"#{i+1} BEFORE  conf={conf:.2f}", fontsize=9)
            axes[i, 0].axis("off")

            axes[i, 1].imshow(crop_after, interpolation="nearest")
            axes[i, 1].set_title(f"#{i+1} AFTER", fontsize=9)
            axes[i, 1].axis("off")

            axes[i, 2].imshow(crop_diff, interpolation="nearest")
            axes[i, 2].set_title(f"#{i+1} DIFF", fontsize=9)
            axes[i, 2].axis("off")

        plt.suptitle(
            f"Per-Aircraft Inpainting Quality — {n_det} detections (zoom {PAD}px padding)",
            fontsize=12, fontweight="bold",
        )
        plt.tight_layout()
        plt.show()

    # Detection details
    if detections:
        print("Detection details:")
        for i, d in enumerate(detections):
            w = d["x2"] - d["x1"]
            h = d["y2"] - d["y1"]
            print(f"  [{i+1}] ({d['x1']:.0f},{d['y1']:.0f})-({d['x2']:.0f},{d['y2']:.0f})  "
                  f"{w:.0f}x{h:.0f}px  conf={d.get('confidence', 0):.3f}  class={d.get('class_name', '?')}")
else:
    print("Inpainting endpoint did not return a clean tile — skipping visualization.")
    print("This may be due to a cold-start timeout or endpoint error.")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC # Model 2 — Delay Prediction
# MAGIC
# MAGIC ## What does this do?
# MAGIC
# MAGIC **For airport operators:** Every active flight in the digital twin gets a predicted delay —
# MAGIC how many extra minutes beyond its scheduled time the aircraft will likely take. This powers the
# MAGIC delay indicators on the flight info panels and FIDS (Flight Information Display System) boards.
# MAGIC Delays are categorized as:
# MAGIC
# MAGIC | Category | Delay | What it means for the ramp |
# MAGIC |----------|-------|---------------------------|
# MAGIC | **On-time** | < 5 min | Normal ops — no action needed |
# MAGIC | **Slight** | 5-15 min | Minor buffer compression — keep an eye on gate turnaround |
# MAGIC | **Moderate** | 15-30 min | Gate hold likely — consider re-assigning connecting flights |
# MAGIC | **Severe** | > 30 min | Cascading impact — notify ground handling, adjust GSE dispatch |
# MAGIC
# MAGIC **For data scientists:** Rule-based heuristic model using 14 features extracted per flight:
# MAGIC
# MAGIC - **Time features (4):** hour_of_day, day_of_week, is_weekend, velocity_normalized
# MAGIC - **One-hot encoded (10):** flight_distance (short/medium/long), altitude (ground/low/cruise), heading quadrant (N/E/S/W)
# MAGIC
# MAGIC The model applies additive delay factors:
# MAGIC
# MAGIC | Factor | Condition | Impact |
# MAGIC |--------|-----------|--------|
# MAGIC | Morning peak | hour in {7, 8, 9} | +15 min |
# MAGIC | Evening peak | hour in {17, 18, 19} | +12 min |
# MAGIC | Ground ops | altitude = "ground" | +8 min |
# MAGIC | Low altitude | altitude = "low" | +3 min |
# MAGIC | Slow moving | velocity < 0.1 (normalized) | +5 min |
# MAGIC | Weekend | day_of_week >= 5 | -3 min |
# MAGIC | Cruising | altitude = "cruise" | -2 min |
# MAGIC
# MAGIC Random noise (uniform +-5 min) is added for realistic variation. Confidence ranges from 0.3 to 0.95
# MAGIC depending on the number of active factors.
# MAGIC
# MAGIC ### Endpoint
# MAGIC
# MAGIC | Method | Path | Query Params |
# MAGIC |--------|------|-------------|
# MAGIC | GET | `/api/predictions/delays` | `icao24` (optional — filter to one flight) |
# MAGIC
# MAGIC **Response:** `{"delays": [{"icao24", "delay_minutes", "confidence", "category"}], "count": N}`

# COMMAND ----------

# ── Delay Prediction: Call Endpoint & Visualize ──────────────────────────────

url = f"{APP_URL}/api/predictions/delays"
print(f"GET {url}")

t0 = time.monotonic()
try:
    resp = httpx.get(url, headers=HEADERS, timeout=30)
    delay_latency_ms = int((time.monotonic() - t0) * 1000)
    print(f"Status: {resp.status_code} ({delay_latency_ms}ms)")

    if resp.status_code != 200:
        print(f"Error: {resp.text[:300]}")
        results["delay"] = {"status": "FAIL", "error": f"HTTP {resp.status_code}", "latency_ms": delay_latency_ms}
        delays = []
    else:
        data = resp.json()
        delays = data.get("delays", [])
        print(f"Flights with predictions: {len(delays)}")
        results["delay"] = {
            "status": "PASS" if delays else "WARN",
            "count": len(delays),
            "latency_ms": delay_latency_ms,
        }
except Exception as e:
    delay_latency_ms = int((time.monotonic() - t0) * 1000)
    print(f"Error: {e}")
    results["delay"] = {"status": "FAIL", "error": str(e), "latency_ms": delay_latency_ms}
    delays = []

if delays:
    # ── Table: first 15 predictions ──
    print(f"\nTop 15 of {len(delays)} predictions:")
    print(f"{'ICAO24':<12} {'Delay':>8} {'Conf':>6} {'Category':<10}")
    print("-" * 40)
    for d in delays[:15]:
        print(f"{d['icao24']:<12} {d['delay_minutes']:>7.1f}m {d['confidence']:>5.2f}  {d['category']:<10}")
    if len(delays) > 15:
        print(f"  ... and {len(delays) - 15} more")

# COMMAND ----------

# ── Delay Prediction: Charts ─────────────────────────────────────────────────
#
# Three visualizations:
#   1. Histogram of predicted delays (min) — expect a right-skewed distribution
#      peaking near 0-10 min with a long tail for severe delays.
#   2. Category breakdown (pie) — in demo mode, expect ~40-60% on-time, ~25% slight.
#   3. Confidence distribution — should cluster between 0.5-0.9.

if delays:
    delay_values = [d["delay_minutes"] for d in delays]
    categories = [d["category"] for d in delays]
    confidences = [d["confidence"] for d in delays]

    fig, axes = plt.subplots(1, 3, figsize=(18, 5))

    # Delay histogram
    axes[0].hist(delay_values, bins=20, color="steelblue", edgecolor="white", alpha=0.85)
    axes[0].axvline(x=5,  color="#2ecc71", linestyle="--", alpha=0.6, label="On-time (<5)")
    axes[0].axvline(x=15, color="#f39c12", linestyle="--", alpha=0.6, label="Moderate (15)")
    axes[0].axvline(x=30, color="#e74c3c", linestyle="--", alpha=0.6, label="Severe (30)")
    axes[0].set_xlabel("Predicted Delay (minutes)")
    axes[0].set_ylabel("Number of flights")
    axes[0].set_title("Delay Distribution")
    axes[0].legend(fontsize=8)

    # Category pie
    cat_colors = {"on_time": "#2ecc71", "slight": "#f1c40f", "moderate": "#e67e22", "severe": "#e74c3c"}
    cat_counts = {}
    for cat in ["on_time", "slight", "moderate", "severe"]:
        cnt = categories.count(cat)
        if cnt > 0:
            cat_counts[cat] = cnt
    axes[1].pie(
        list(cat_counts.values()),
        labels=[f"{k}\n({v})" for k, v in cat_counts.items()],
        colors=[cat_colors[k] for k in cat_counts],
        autopct="%1.0f%%", startangle=90,
    )
    axes[1].set_title("Category Breakdown")

    # Confidence histogram
    axes[2].hist(confidences, bins=15, color="#9b59b6", edgecolor="white", alpha=0.85)
    axes[2].set_xlabel("Confidence Score")
    axes[2].set_ylabel("Number of flights")
    axes[2].set_title("Confidence Distribution")

    plt.suptitle(f"Delay Predictions — {len(delays)} flights", fontsize=13)
    plt.tight_layout()
    plt.show()

    # Summary stats
    avg_delay = sum(delay_values) / len(delay_values)
    max_delay = max(delay_values)
    avg_conf = sum(confidences) / len(confidences)
    print(f"\nSummary: avg delay={avg_delay:.1f}m, max={max_delay:.1f}m, "
          f"avg confidence={avg_conf:.2f}, flights={len(delays)}")
    results["delay"]["avg_delay_min"] = round(avg_delay, 1)
    results["delay"]["max_delay_min"] = round(max_delay, 1)
else:
    print("No delay predictions returned — app may not have active flights.")

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC # Model 3 — Gate Recommendation
# MAGIC
# MAGIC ## What does this do?
# MAGIC
# MAGIC **For airport operators:** When an arriving flight needs a gate, this model recommends the best
# MAGIC available gate based on multiple factors. This supports ramp controllers in making efficient
# MAGIC gate assignments that minimize taxi time, balance terminal load, and account for international
# MAGIC vs. domestic routing requirements.
# MAGIC
# MAGIC A good gate assignment means:
# MAGIC - Shorter taxi time = less fuel burn, less runway occupancy, less ground congestion
# MAGIC - Correct terminal = passengers arrive at the right immigration/customs area
# MAGIC - Available gate = no ground stops waiting for a gate to clear
# MAGIC
# MAGIC **For data scientists:** Weighted scoring algorithm (not ML-trained — deterministic heuristic):
# MAGIC
# MAGIC | Factor | Weight | Logic |
# MAGIC |--------|--------|-------|
# MAGIC | **Availability** | 50% | `AVAILABLE` = 0.5, `DELAYED` = 0.2, `OCCUPIED`/`MAINTENANCE` = excluded |
# MAGIC | **Terminal match** | 25% | International flight + Terminal B = 0.25, domestic + Terminal A = 0.25 |
# MAGIC | **Runway proximity** | 15% | Lower gate number = closer to runway = higher score |
# MAGIC | **Delay penalty** | 10% | Flights with >30 min delay get -0.1 (deprioritize tight turnarounds) |
# MAGIC
# MAGIC International detection: callsign prefix NOT in {AAL, UAL, DAL, SWA, JBU, NKS, ASA, FFT, SKW}.
# MAGIC
# MAGIC ### Endpoint
# MAGIC
# MAGIC | Method | Path | Params |
# MAGIC |--------|------|--------|
# MAGIC | GET | `/api/predictions/gates/{icao24}` | `top_k` (default 3, max 10) |
# MAGIC
# MAGIC **Response:** `[{"gate_id", "score", "reasons": [...], "taxi_time"}]`

# COMMAND ----------

# ── Gate Recommendation: Call Endpoint & Visualize ───────────────────────────
#
# Strategy: pick the first arriving (not on ground) flight from the active set.
# If all are on ground, pick the first flight.

# Step 1: Get active flights
flights_url = f"{APP_URL}/api/flights"
print(f"GET {flights_url}")

flights_resp = httpx.get(flights_url, headers=HEADERS, timeout=30)
flights = []
if flights_resp.status_code == 200:
    fdata = flights_resp.json()
    flights = fdata.get("flights", fdata) if isinstance(fdata, dict) else fdata
    print(f"Active flights: {len(flights)}")

# Step 2: Select a flight
selected_icao24 = None
if flights:
    arriving = [f for f in flights if not f.get("on_ground", True)]
    selected = arriving[0] if arriving else flights[0]
    selected_icao24 = selected.get("icao24", "unknown")
    print(f"Selected flight: {selected_icao24} (callsign: {selected.get('callsign', '?')})")

# Step 3: Call gate recommendation
recommendations = []
gate_latency_ms = 0
if selected_icao24:
    TOP_K = 5
    url = f"{APP_URL}/api/predictions/gates/{selected_icao24}?top_k={TOP_K}"
    print(f"\nGET {url}")

    t0 = time.monotonic()
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=30)
        gate_latency_ms = int((time.monotonic() - t0) * 1000)
        print(f"Status: {resp.status_code} ({gate_latency_ms}ms)")

        if resp.status_code == 200:
            recommendations = resp.json()
            results["gate"] = {
                "status": "PASS" if recommendations else "WARN",
                "count": len(recommendations),
                "latency_ms": gate_latency_ms,
                "flight": selected_icao24,
            }
        else:
            print(f"Error: {resp.text[:300]}")
            results["gate"] = {"status": "FAIL", "error": f"HTTP {resp.status_code}", "latency_ms": gate_latency_ms}
    except Exception as e:
        gate_latency_ms = int((time.monotonic() - t0) * 1000)
        results["gate"] = {"status": "FAIL", "error": str(e), "latency_ms": gate_latency_ms}
else:
    results["gate"] = {"status": "SKIP", "error": "No active flights"}

# Display results
if recommendations:
    print(f"\nGate recommendations for {selected_icao24}:")
    print(f"{'Rank':<5} {'Gate':<6} {'Score':>6} {'Taxi':>6} {'Reasons'}")
    print("-" * 70)
    for i, rec in enumerate(recommendations):
        reasons_str = "; ".join(rec.get("reasons", []))
        print(f"  {i+1:<3} {rec['gate_id']:<6} {rec['score']:>5.2f} {rec['taxi_time']:>4}m  {reasons_str}")

    # Chart
    gate_ids = [r["gate_id"] for r in recommendations]
    scores = [r["score"] for r in recommendations]
    taxi_times = [r["taxi_time"] for r in recommendations]

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    bar_colors = ["#2ecc71" if s == max(scores) else "#3498db" for s in scores]
    bars = axes[0].barh(gate_ids[::-1], scores[::-1], color=bar_colors[::-1], edgecolor="white")
    axes[0].set_xlabel("Recommendation Score")
    axes[0].set_xlim(0, 1.05)
    axes[0].set_title(f"Gate Scores (flight: {selected_icao24})")
    for bar, score in zip(bars, scores[::-1]):
        axes[0].text(bar.get_width() + 0.02, bar.get_y() + bar.get_height() / 2,
                     f"{score:.2f}", va="center", fontsize=10)

    axes[1].barh(gate_ids[::-1], taxi_times[::-1], color="#e67e22", edgecolor="white")
    axes[1].set_xlabel("Estimated Taxi Time (min)")
    axes[1].set_title("Taxi Time per Gate")
    for i, (g, t) in enumerate(zip(gate_ids[::-1], taxi_times[::-1])):
        axes[1].text(t + 0.15, i, f"{t}m", va="center", fontsize=10)

    plt.suptitle(f"Gate Recommendation for {selected_icao24}", fontsize=12)
    plt.tight_layout()
    plt.show()

    best = recommendations[0]
    results["gate"]["best_gate"] = best["gate_id"]
    results["gate"]["best_score"] = best["score"]

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC # Model 4 — Congestion Prediction
# MAGIC
# MAGIC ## What does this do?
# MAGIC
# MAGIC **For airport operators:** This model provides a real-time heat map of airport congestion.
# MAGIC It monitors six operational areas (two runways, two taxiways, two aprons) and classifies
# MAGIC each by how close it is to capacity. This is the same information displayed on the ATC
# MAGIC ground radar overlay in the digital twin.
# MAGIC
# MAGIC | Level | What it means on the ramp |
# MAGIC |-------|--------------------------|
# MAGIC | **LOW** (green) | Normal flow — no action needed |
# MAGIC | **MODERATE** (yellow) | Slight congestion — expect minor taxi delays |
# MAGIC | **HIGH** (orange) | Bottleneck forming — hold departures or reroute taxiing aircraft |
# MAGIC | **CRITICAL** (red) | At capacity — ground stop on affected area, coordinate with tower |
# MAGIC
# MAGIC **For data scientists:** Capacity threshold model — counts flights in each geographic bounding box
# MAGIC using position and velocity filters (e.g., taxiway = on ground + velocity > 2 m/s), then classifies
# MAGIC the ratio against capacity thresholds (50%/75%/90%).
# MAGIC
# MAGIC Wait time estimation uses area-type-specific lookup tables:
# MAGIC
# MAGIC | Area Type | Capacity | MODERATE wait | HIGH wait | CRITICAL wait |
# MAGIC |-----------|----------|---------------|-----------|---------------|
# MAGIC | Runway | 2 | 3 min | 8 min | 15 min |
# MAGIC | Taxiway | 5 | 2 min | 5 min | 10 min |
# MAGIC | Apron | 10 | 1 min | 3 min | 5 min |
# MAGIC
# MAGIC ### Endpoints
# MAGIC
# MAGIC | Method | Path | Returns |
# MAGIC |--------|------|---------|
# MAGIC | GET | `/api/predictions/congestion` | All areas |
# MAGIC | GET | `/api/predictions/bottlenecks` | Only HIGH + CRITICAL areas |
# MAGIC | GET | `/api/predictions/congestion-summary` | Both in one call |
# MAGIC
# MAGIC **Response:** `{"areas": [{"area_id", "area_type", "level", "flight_count", "capacity", "wait_minutes"}], "bottlenecks": [...], "areas_count", "bottlenecks_count"}`

# COMMAND ----------

# ── Congestion: Call Endpoint & Visualize ────────────────────────────────────

url = f"{APP_URL}/api/predictions/congestion-summary"
print(f"GET {url}")

t0 = time.monotonic()
try:
    resp = httpx.get(url, headers=HEADERS, timeout=30)
    congestion_latency_ms = int((time.monotonic() - t0) * 1000)
    print(f"Status: {resp.status_code} ({congestion_latency_ms}ms)")

    if resp.status_code != 200:
        print(f"Error: {resp.text[:300]}")
        results["congestion"] = {"status": "FAIL", "error": f"HTTP {resp.status_code}", "latency_ms": congestion_latency_ms}
        areas = []
        bottlenecks = []
    else:
        cdata = resp.json()
        areas = cdata.get("areas", [])
        bottlenecks = cdata.get("bottlenecks", [])
        print(f"Areas: {len(areas)}, Bottlenecks: {len(bottlenecks)}")
        results["congestion"] = {
            "status": "PASS" if areas else "WARN",
            "areas": len(areas),
            "bottlenecks": len(bottlenecks),
            "latency_ms": congestion_latency_ms,
        }
except Exception as e:
    congestion_latency_ms = int((time.monotonic() - t0) * 1000)
    print(f"Error: {e}")
    results["congestion"] = {"status": "FAIL", "error": str(e), "latency_ms": congestion_latency_ms}
    areas = []
    bottlenecks = []

if areas:
    # ── Area table ──
    print(f"\n{'Area':<25} {'Type':<10} {'Level':<10} {'Flights':>8} {'Capacity':>9} {'Util':>6} {'Wait':>6}")
    print("-" * 80)
    for a in areas:
        util = (a["flight_count"] / a["capacity"] * 100) if a["capacity"] > 0 else 0
        marker = "!!" if a["level"] in ("high", "critical") else "  "
        print(f"{marker}{a['area_id']:<23} {a['area_type']:<10} {a['level'].upper():<10} "
              f"{a['flight_count']:>8} {a['capacity']:>9} {util:>5.0f}% {a['wait_minutes']:>4}m")

    if bottlenecks:
        print(f"\nBottlenecks requiring attention: {len(bottlenecks)}")
        for b in bottlenecks:
            print(f"  {b['area_id']} ({b['area_type']}): {b['level'].upper()} "
                  f"— {b['flight_count']}/{b['capacity']} flights, {b['wait_minutes']}m wait")
    else:
        print("\nNo bottlenecks — all areas below HIGH threshold.")

    # ── Charts ──
    LEVEL_COLORS = {"low": "#2ecc71", "moderate": "#f1c40f", "high": "#e67e22", "critical": "#e74c3c"}

    fig, axes = plt.subplots(1, 2, figsize=(16, max(4, len(areas) * 0.7)))

    area_ids = [a["area_id"] for a in areas]
    utilizations = [(a["flight_count"] / a["capacity"] * 100) if a["capacity"] > 0 else 0 for a in areas]
    colors = [LEVEL_COLORS.get(a["level"], "gray") for a in areas]

    # Utilization
    bars = axes[0].barh(area_ids[::-1], utilizations[::-1], color=colors[::-1], edgecolor="white")
    axes[0].axvline(x=50, color="#f1c40f", linestyle="--", alpha=0.4, label="Moderate (50%)")
    axes[0].axvline(x=75, color="#e67e22", linestyle="--", alpha=0.4, label="High (75%)")
    axes[0].axvline(x=90, color="#e74c3c", linestyle="--", alpha=0.4, label="Critical (90%)")
    axes[0].set_xlabel("Utilization (%)")
    axes[0].set_xlim(0, 110)
    axes[0].set_title("Area Utilization")
    axes[0].legend(fontsize=8, loc="lower right")
    for bar, u in zip(bars, utilizations[::-1]):
        axes[0].text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                     f"{u:.0f}%", va="center", fontsize=9)

    # Wait times
    wait_times = [a["wait_minutes"] for a in areas]
    axes[1].barh(area_ids[::-1], wait_times[::-1], color=colors[::-1], edgecolor="white")
    axes[1].set_xlabel("Estimated Wait (min)")
    axes[1].set_title("Wait Times")
    legend_patches = [mpatches.Patch(color=LEVEL_COLORS[lv], label=lv.upper()) for lv in LEVEL_COLORS]
    axes[1].legend(handles=legend_patches, fontsize=8, loc="lower right")
    for bar, wt in zip(axes[1].patches, wait_times[::-1]):
        if wt > 0:
            axes[1].text(bar.get_width() + 0.1, bar.get_y() + bar.get_height() / 2,
                         f"{wt}m", va="center", fontsize=9)

    plt.suptitle(f"Airport Congestion — {len(areas)} areas", fontsize=12)
    plt.tight_layout()
    plt.show()

# COMMAND ----------

# MAGIC %md
# MAGIC ---
# MAGIC # Summary

# COMMAND ----------

# ── Final Summary Report ─────────────────────────────────────────────────────
#
# Aggregate results from all four models.  Exit with an assertion error if
# any model returned FAIL so the Databricks job surfaces the failure.

print("=" * 70)
print("  ML ENDPOINT VALIDATION SUMMARY")
print("=" * 70)
print(f"  Timestamp:  {datetime.now(timezone.utc).isoformat()}")
print(f"  App URL:    {APP_URL}")
print(f"  Airport:    {AIRPORT_IATA_RESOLVED}")
print()

all_pass = True
for model, info in results.items():
    status = info.get("status", "?")
    latency = info.get("latency_ms", "?")
    if status == "FAIL":
        all_pass = False
    icon = {"PASS": "[OK]", "WARN": "[!!]", "FAIL": "[XX]", "SKIP": "[--]"}.get(status, "[??]")

    detail_parts = []
    for k, v in info.items():
        if k not in ("status", "latency_ms", "error"):
            detail_parts.append(f"{k}={v}")
    detail = ", ".join(detail_parts)

    print(f"  {icon} {model:<20} {status:<6} {latency:>6}ms  {detail}")
    if info.get("error"):
        print(f"       Error: {info['error']}")

print()
print("=" * 70)

if not all_pass:
    failing = [m for m, i in results.items() if i.get("status") == "FAIL"]
    msg = f"FAILED models: {', '.join(failing)}"
    print(f"  RESULT: FAIL — {msg}")
    print("=" * 70)
    raise AssertionError(msg)
else:
    print("  RESULT: ALL MODELS PASSED")
    print("=" * 70)
