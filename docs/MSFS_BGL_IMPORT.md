# MSFS BGL Airport Import & Lakehouse Persistence

How to import airport scenery from Microsoft Flight Simulator (MSFS) BGL files and persist them to the Databricks Lakehouse (Unity Catalog).

## Overview

The digital twin supports importing detailed airport layouts from MSFS community scenery packages. These packages contain compiled BGL files with high-fidelity gate positions, runway geometry, taxiway networks, and apron areas — often more detailed than OpenStreetMap data.

### Architecture

```
                        ┌─────────────────────────────────┐
  BGL/ZIP file          │  Two import paths:               │
  (from flightsim.to)   │                                  │
        │               │  1. HTTP API  (live app)         │
        │               │  2. Databricks Job (batch)       │
        ▼               └─────────────────────────────────┘

  ┌──────────┐     parse      ┌──────────┐    convert     ┌──────────┐
  │ BGL/ZIP  │ ──────────────▶│ MSFSDoc  │──────────────▶ │  Config  │
  │ (binary) │   MSFSParser   │ (model)  │  MSFSConverter │  (dict)  │
  └──────────┘                └──────────┘                └────┬─────┘
                                                               │
                              ┌─────────────────────────┐      │ persist
                              │    Unity Catalog         │◀────┘
                              │  airport_metadata        │
                              │  gates                   │
                              │  runways                 │
                              │  terminals               │
                              │  taxiways                │
                              │  aprons                  │
                              └─────────────────────────┘
```

### Supported Formats

| Format | Extension | Detection |
|--------|-----------|-----------|
| Compiled BGL | `.bgl` | Magic bytes `0x19920201` |
| ZIP archive | `.zip` | Magic bytes `PK\x03\x04` — scans for `.bgl` then `.xml` inside |
| MSFS XML | `.xml` | `<FSData>` root with `<Airport>` elements |

## Obtaining BGL Files

MSFS community scenery packages are available from [flightsim.to](https://flightsim.to/). Each package typically contains a ZIP with one or more compiled `.bgl` files inside.

1. Search for the airport by ICAO code (e.g., "LGAV", "LSGG")
2. Download the scenery package (ZIP file)
3. The ZIP contains compiled BGL files with parking spots, runways, and taxiway networks

The parser auto-detects the format, so you can upload the ZIP directly — no need to extract the BGL first.

## Import Path 1: HTTP API (Live App)

Upload a BGL/ZIP file directly to the running app via the REST API. The app parses it, merges with any existing config, and persists to both Unity Catalog and Lakebase cache.

### Endpoint

```
POST /api/airport/import/msfs
```

### Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `merge` | bool | `true` | Merge with existing airport config (false = replace) |
| `icao_code` | string | auto | Explicit ICAO code — overrides filename detection |
| `filename` | string | auto | Original filename hint for ICAO extraction |

The ICAO code is resolved in this order:
1. `icao_code` query parameter (if provided)
2. Extracted from the BGL data
3. Extracted from `filename` or `Content-Disposition` header (regex matches 4-letter ICAO patterns like `lgav-airport.zip` -> `LGAV`)

### Examples

**Upload with explicit ICAO code (recommended):**
```bash
curl -X POST "https://your-app.databricksapps.com/api/airport/import/msfs?icao_code=LGAV" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @lgav-eleftherios-venizelos-intl.zip
```

**Upload with filename hint:**
```bash
curl -X POST "https://your-app.databricksapps.com/api/airport/import/msfs?filename=lgav-airport.zip" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @lgav-eleftherios-venizelos-intl.zip
```

**Replace existing config instead of merging:**
```bash
curl -X POST "https://your-app.databricksapps.com/api/airport/import/msfs?icao_code=LSGG&merge=false" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @lsgg-geneva.zip
```

### Response

```json
{
  "success": true,
  "icaoCode": "LGAV",
  "gatesImported": 157,
  "taxiwaysImported": 0,
  "runwaysImported": 2,
  "apronsImported": 12,
  "warnings": [],
  "timestamp": "2026-03-20T20:24:33.927Z"
}
```

### What happens on import

1. Request body is read as raw bytes
2. `MSFSParser.parse()` auto-detects format (BGL, ZIP, or XML)
3. For ZIPs: extracts and parses all `.bgl` files inside, falls back to `.xml`
4. `MSFSConverter.to_config()` converts the parsed model to the internal config dict (gates with lat/lon, runways, aprons, etc.)
5. Config is persisted to Unity Catalog via `AirportRepository.save_airport_config()`
6. Config is cached in Lakebase for fast reads

## Import Path 2: Databricks Job (Batch Persistence)

For bulk imports or when the app is not running, upload BGL files to a Unity Catalog volume and run a Databricks job to parse and persist them.

### Step 1: Upload BGL files to the UC Volume

The volume path for MSFS scenery files:
```
/Volumes/serverless_stable_3n0ihb_catalog/airport_digital_twin/simulation_data/msfs_scenery/
```

**Using Databricks CLI:**
```bash
databricks fs cp ./lgav-airport.zip \
  dbfs:/Volumes/serverless_stable_3n0ihb_catalog/airport_digital_twin/simulation_data/msfs_scenery/lgav.zip \
  --profile FEVM_SERVERLESS_STABLE
```

**Using the REST Files API (if CLI has issues with volume paths):**
```bash
# Get auth token
TOKEN=$(databricks auth token --profile FEVM_SERVERLESS_STABLE | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")
HOST="https://fevm-serverless-stable-3n0ihb.cloud.databricks.com"

# Upload file
curl -X PUT "$HOST/api/2.0/fs/files/Volumes/serverless_stable_3n0ihb_catalog/airport_digital_twin/simulation_data/msfs_scenery/lgav.zip" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @lgav-airport.zip
```

A successful upload returns HTTP 204 (No Content).

### Step 2: Register the file in the persistence notebook

Edit `databricks/notebooks/persist_msfs_bgl.py` and add the new file to the `SCENERY_FILES` dict:

```python
SCENERY_FILES = {
    "lsgg.zip": "LSGG",
    "lgav.zip": "LGAV",
    "rjtt.zip": "RJTT",   # <-- add new entries here
}
```

The key is the filename in the volume, the value is the ICAO code.

### Step 3: Deploy and run the job

```bash
# Deploy the updated notebook to the workspace
databricks bundle deploy --target dev --profile FEVM_SERVERLESS_STABLE

# Run the existing job (ID: 1108080229108946)
databricks jobs run-now --profile FEVM_SERVERLESS_STABLE 1108080229108946
```

Or create a new one-time job:

```bash
databricks jobs create --profile FEVM_SERVERLESS_STABLE --json '{
  "name": "Persist MSFS BGL Airports",
  "tasks": [{
    "task_key": "persist_msfs_bgl",
    "notebook_task": {
      "notebook_path": "/Workspace/Users/laurent.prat@databricks.com/.bundle/airport-digital-twin/dev/files/databricks/notebooks/persist_msfs_bgl",
      "source": "WORKSPACE"
    },
    "environment_key": "default"
  }],
  "environments": [{
    "environment_key": "default",
    "spec": {
      "client": "1",
      "dependencies": ["databricks-sdk", "databricks-sql-connector"]
    }
  }]
}'
```

### Step 4: Verify persistence

Query the Unity Catalog tables to confirm:

```sql
-- Check airport metadata
SELECT icao_code, name, data_sources, updated_at
FROM serverless_stable_3n0ihb_catalog.airport_digital_twin.airport_metadata
WHERE icao_code IN ('LSGG', 'LGAV')
ORDER BY updated_at DESC;

-- Check gate counts
SELECT icao_code, COUNT(*) as gate_count
FROM serverless_stable_3n0ihb_catalog.airport_digital_twin.gates
WHERE icao_code IN ('LSGG', 'LGAV')
GROUP BY icao_code;

-- Check runway counts
SELECT icao_code, COUNT(*) as runway_count
FROM serverless_stable_3n0ihb_catalog.airport_digital_twin.runways
WHERE icao_code IN ('LSGG', 'LGAV')
GROUP BY icao_code;
```

## How the BGL Parser Works

The parser (`src/formats/msfs/bgl_parser.py`) decodes the binary BGL format:

1. **Header validation**: checks magic bytes `0x19920201`
2. **Section table**: reads section headers to find the AIRPORT section (type `0x03`)
3. **Airport record**: extracts coordinates, name, and sub-records
4. **Parking spots** (record type `0x00E7`): each spot has a flags bitfield encoding name index, parking type (GATE/RAMP/DOCK), number, and airline codes
5. **Runways** (record type `0x00CE`): center position, length, width, heading, surface type

BGL coordinates use a custom encoding:
```
longitude = raw_int32 * (360.0 / (3 * 0x10000000)) - 180.0
latitude  = 90.0 - raw_int32 * (180.0 / (2 * 0x10000000))
```

The converter (`src/formats/msfs/converter.py`) then transforms the parsed model into the internal config format with WGS84 lat/lon coordinates for each gate, runway endpoint, and apron vertex.

## Currently Persisted BGL Airports

| ICAO | Airport | Gates | Runways | Source |
|------|---------|-------|---------|--------|
| LSGG | Geneva Cointrin | 94 | 1 | flightsim.to |
| LGAV | Eleftherios Venizelos Intl | 157 | 2 | flightsim.to |

## 3-Tier Loading Order

When the app activates an airport, it loads config in this order:

1. **Lakebase cache** (Postgres, <10ms) — fastest, populated on any successful import
2. **Unity Catalog tables** — full persistence, populated by the job or API import
3. **OSM Overpass API** — fallback, fetches live data (10-60s)

BGL-imported airports are available in tiers 1 and 2 after import, avoiding the slow OSM fetch on subsequent activations.

## Troubleshooting

### "No valid MSFS airport scenery found in ZIP archive"
The ZIP does not contain any `.bgl` or valid `.xml` files with airport data. Verify the download is a valid MSFS scenery package.

### ICAO code is empty after import
Pass `icao_code` explicitly — BGL files often don't embed the ICAO code internally. The parser tries to extract it from the filename, but unusual naming may not match.

### Gates count is 0
The BGL file may only contain ramp positions (general aviation) without gate-type parking. Only parking spots typed as `GATE_SMALL`, `GATE_MEDIUM`, `GATE_HEAVY`, or `GATE_EXTRA` are classified as gates.

### Volume upload returns 404
Ensure the volume path exists. The parent volume `simulation_data` and directory `msfs_scenery` must already exist in Unity Catalog. Create them via the Databricks UI or SQL:
```sql
CREATE VOLUME IF NOT EXISTS serverless_stable_3n0ihb_catalog.airport_digital_twin.simulation_data;
```
