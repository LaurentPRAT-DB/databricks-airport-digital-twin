# Plan: OBT Model Evaluation from Lakebase (EDDF Real Data)

**Status:** Backlog
**Date added:** 2026-04-07
**Depends on:** OAuth Token Refresh fix, OpenSky Event Inference Pipeline
**Scope:** Update evaluation script to query Lakebase instead of local JSONL files

---

## Context

The OBT model was trained on 33 airports including FRA (EDDF's IATA code) with T-park MAE of 8.39 min. EDDF real ADS-B data is being collected via the OpenSky collector and stored as raw snapshots in Lakebase (`flight_position_snapshots` with `data_source='opensky'`). The goal is to evaluate the model against real turnaround observations.

The collector writes raw snapshots only — no phase transitions or gate assignments. The enrichment pipeline (`OpenSkyEventInferrer` + OSM gate matching) exists but only runs in the recording endpoint. The evaluation script (`scripts/evaluate_obt_eddf.py`) currently reads from local JSONL files.

## Approach

Update `scripts/evaluate_obt_eddf.py` to add a `--from-lakebase` mode that:

1. Queries raw OpenSky snapshots from Lakebase for EDDF
2. Groups by timestamp into frames
3. Runs `OpenSkyEventInferrer` (with OSM gates) to detect phase transitions + gate assignments
4. Extracts complete turnarounds (parked → pushback)
5. Builds OBT features with gate info and compares predictions vs actual

## File to Modify

`scripts/evaluate_obt_eddf.py`

## Changes

### 1. Add Lakebase Query Function

```python
def load_from_lakebase(airport_icao: str, days: int = 7) -> list[dict]:
    """Query raw OpenSky snapshots from Lakebase for an airport."""
```

Uses `LakebaseService._get_read_connection()` to query:

```sql
SELECT icao24, callsign, latitude, longitude, altitude, velocity,
       heading, vertical_rate, on_ground, aircraft_type, snapshot_time
FROM flight_position_snapshots
WHERE airport_icao = %s AND data_source = 'opensky'
  AND snapshot_time > NOW() - INTERVAL '%s days'
ORDER BY snapshot_time, icao24
```

Reuses existing LakebaseService connection machinery (OAuth, pool, read replica).

### 2. Convert Lakebase Rows to Inferrer Format

Reuse existing `group_into_frames()` — just need to map Lakebase column names to the expected snapshot format (velocity in m/s → kts, altitude in m → ft, etc.). Check what units the collector stores (it passes through from `OpenSkyService.fetch_flights` which already converts to kts/ft).

### 3. Wire Up `--from-lakebase` CLI Flag

```python
parser.add_argument("--from-lakebase", action="store_true",
                    help="Read from Lakebase instead of local JSONL files")
parser.add_argument("--days", type=int, default=7,
                    help="How many days of data to query (default: 7)")
```

When `--from-lakebase` is set, call `load_from_lakebase()` instead of `load_jsonl_files()`. The rest of the pipeline (gate fetch, frame grouping, event inference, OBT evaluation) is identical.

### 4. Use `airport_iata='FRA'` for OBT Features

The model was trained with IATA codes. The script already accepts `--iata FRA` (default). No change needed — just ensure this is passed to `build_feature_set()`.

## What NOT to Change

- No changes to `lakebase_service.py` — use direct psycopg2 connection (same as the script currently does for OSM fetch)
- No changes to the collector — it already writes the data we need
- No changes to `OpenSkyEventInferrer` — it already handles the enrichment
- No new API endpoints — this is a CLI evaluation tool

## Verification

```bash
# Run from Lakebase (EDDF data collected by the app)
uv run python scripts/evaluate_obt_eddf.py --from-lakebase --days 7

# Compare with local file mode (still works)
uv run python scripts/evaluate_obt_eddf.py --include-synced
```

Expected output: turnaround table with observed vs predicted durations, MAE/RMSE/bias summary. With sparse data (< 24h collection), expect few complete turnarounds. With 24h+ of continuous data, expect 30-100+ turnarounds at EDDF.
