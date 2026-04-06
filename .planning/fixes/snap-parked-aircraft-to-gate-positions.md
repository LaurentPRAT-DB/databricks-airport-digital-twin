# Fix: Snap Parked Aircraft to Gate Positions in Recorded Data

**Status:** Fix
**Date added:** 2026-04-06
**Scope:** Backend — snap raw ADS-B positions to gate coords when aircraft is parked

---

## Context

In recorded (OpenSky ADS-B) mode, parked aircraft render inside terminal buildings because their raw ADS-B ground positions are inaccurate. The `OpenSkyEventInferrer` correctly identifies the nearest gate and assigns it, but the aircraft's lat/lon in the frame data remains the raw ADS-B position. This causes UAL2015 at SFO to appear inside a terminal building despite being assigned to gate G1.

## Approach

Snap aircraft positions to their assigned gate coordinates when they are parked. Two locations need changes:

### 1. `src/inference/opensky_events.py` — Enriched snapshots (line ~282-297)

Add a gate position lookup dict in `__init__` and use it when emitting enriched snapshots for parked aircraft:

- Add `self._gate_coords: dict[str, tuple[float, float]]` mapping `gate_id -> (lat, lon)`
- In `process_frame()`, when phase is `"parked"` and `tracker.assigned_gate` is set, replace lat/lon in the enriched snapshot with the gate coordinates

### 2. `app/backend/api/opensky.py` — Frame snapshots sent to frontend (lines 657-669)

The existing gate assignment loop already iterates frames. Extend it to also snap positions:

- Build a `gate_coords` dict from the gates config (already loaded at line 648)
- When assigning a gate to a frame snapshot, also check if `snap["on_ground"]` and velocity is low (~0), then replace `snap["latitude"]`/`snap["longitude"]` with the gate coordinates

## Files to Modify

| File | Change |
|------|--------|
| `src/inference/opensky_events.py` | Snap enriched snapshot positions for parked aircraft |
| `app/backend/api/opensky.py` | Snap frame positions for gate-assigned aircraft |

## Verification

1. `uv run pytest tests/ -v -k "opensky_event" --tb=short` — existing inference tests pass
2. `uv run pytest tests/ -v -k "recorded" --tb=short` — recorded data tests pass
3. Visual: reload recorded KSFO data in the app — parked aircraft should appear at gate positions, not inside buildings
