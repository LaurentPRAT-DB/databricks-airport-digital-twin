# Fix: OAuth Token Refresh + OBT Evaluation Script for EDDF

**Status:** Fix
**Date added:** 2026-04-07
**Scope:** Collector token refresh bug + new evaluation script + EDDF re-collection

---

## Context

We collected 4h of OpenSky ADS-B data for EDDF but only got ~30min of usable data (241 records, 10 aircraft) because the OAuth token expired after ~1h and was never refreshed. We need to:

1. Fix the token refresh bug so the next run captures full 4h
2. Build an evaluation script to run the OpenSky event inferrer on collected data and compare observed turnaround durations against the current OBT model predictions (which are fallback-only for EDDF: narrow=45min, wide=90min, regional=35min)

## Task 1: Fix OAuth Token Refresh in Collector

**File:** `scripts/opensky_collector.py`

**Problem:** Lines 220-247 — `_oauth_token` is cached globally, `get_oauth_token()` returns cached token forever. OpenSky tokens expire (~1h). After expiry, all requests get 401.

**Fix:**

- Track token expiry time (parse `expires_in` from token response, or default to 3000s)
- In `get_oauth_token()`, check if token is expired/near-expiry before returning cached value
- On 401 errors in the collection loop, invalidate the cached token so next fetch re-authenticates

**Changes:**

- Replace `_oauth_token: str | None` with a dataclass/tuple holding `(token, expires_at)`
- `get_oauth_token()` checks `time.time() < expires_at - 60` (60s buffer) before returning cached
- In the 401 error path inside the collection loop, reset the cached token

## Task 2: OBT Evaluation Script

**File:** `scripts/evaluate_obt_eddf.py` (new)

**Pipeline:**

1. Load all `EDDF_*.jsonl` files from `data/opensky_raw/`
2. Fetch EDDF gate positions from OSM (using `src/formats/osm/parser.py` OSMParser + `src/formats/osm/converter.py` OSMConverter)
3. Feed time-ordered frames through `OpenSkyEventInferrer` (from `src/inference/opensky_events.py`)
   - Note: raw OpenSky velocity is in m/s, but inferrer expects kts (it converts back via `/ 1.94384`). Need to convert m/s → kts before feeding.
4. Extract `phase_transitions` and `gate_events` → compute observed turnaround durations (parked→pushback delta)
5. For each observed turnaround, build `OBTFeatureSet` and get the current model prediction (will be fallback since no trained model for EDDF)
6. Print comparison table: callsign, gate, observed turnaround, predicted turnaround, error

**Key dependencies:**

- `src/inference/opensky_events.py` — `OpenSkyEventInferrer` (needs gate list as `[{"ref": ..., "geo": {"latitude": ..., "longitude": ...}}]`)
- `src/formats/osm/parser.py:OSMParser` + `src/formats/osm/converter.py:OSMConverter` — fetch EDDF gates from Overpass
- `src/ml/obt_model.py:OBTPredictor` — predict turnaround (fallback mode)
- `src/ml/obt_features.py:OBTFeatureSet`, `classify_aircraft` — build features

**Unit conversion:** Raw OpenSky velocity is m/s. The inferrer's `process_frame()` expects velocity in kts (line 213: `velocity_kts / 1.94384`). So we must convert `velocity_ms * 1.94384` before feeding.

## Task 3: Re-run Collector

After fixing the token refresh, re-run:

```bash
OPENSKY_CLIENT_ID=... OPENSKY_CLIENT_SECRET=... uv run python scripts/opensky_collector.py --airport EDDF --duration 14400
```

## Verification

1. **Token refresh:** grep logs for "OAuth2 token" — should see re-auth after ~1h, no 401 cascade
2. **Evaluation script:** run on existing sparse data to verify pipeline works (even if few turnarounds found), then re-run on full dataset
3. **Existing tests pass:** `uv run pytest tests/ -k opensky -v`
