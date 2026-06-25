# Pass all airport data to demo subprocess

**Status:** planned
**Priority:** P0
**Area:** simulation, demo

## Context

The demo simulation subprocess (`_run_engine_subprocess` in `demo_simulation_service.py`) runs via `multiprocessing.get_context("spawn")` — completely isolated memory. It has NO access to `airport_config_service` (parent-only singleton).

Current state after first fix (commit d80f886): OSM runway data is passed and monkey-patched. Approach directions are correct.

**Remaining problem:** Gates, taxiway graph, and terminal data are NOT passed. The subprocess creates a fresh empty `airport_config_service` instance (`_current_config = {}`) so `get_gates()` falls back to synthetic 2-concourse grid (A1-A10, B1-B10) around airport center. After landing, aircraft jump from the real runway position to a fake gate position that doesn't match the airport layout.

## Data audit — what the subprocess needs

| Data | Source in parent | Subprocess gets | Impact |
|------|-----------------|-----------------|--------|
| OSM runway | `config["osmRunways"]` | ✅ Patched | Approach direction fixed |
| OSM gates | `config["gates"]` | ❌ Empty → fake grid | **P0: taxi jump** |
| Taxiway graph | `service.taxiway_graph` | ❌ None → geometry fallback | Medium: taxi paths not realistic but functional |
| Terminals | `config["terminals"]` | ❌ Empty → face center | Low: visual only |

## Fix

Single change in `_run_engine_subprocess`: also pass OSM gate data and inject it into `fallback._loaded_gates` before engine init.

### In `generate_demo_isolated` (parent process):

```python
# After reading osm_runway, also read gates
osm_gates = None
try:
    from app.backend.services.airport_config_service import get_airport_config_service
    service = get_airport_config_service()
    config = service.get_config()
    raw_gates = config.get("gates", [])
    if raw_gates:
        osm_gates = {}
        for gate in raw_gates:
            ref = gate.get("ref") or gate.get("id")
            geo = gate.get("geo", {})
            lat = geo.get("latitude")
            lon = geo.get("longitude")
            if ref and lat and lon:
                ref_str = str(ref)
                numeric_part = "".join(c for c in ref_str if c.isdigit())
                if numeric_part and int(numeric_part) > 200:
                    continue
                osm_gates[ref_str] = (float(lat), float(lon))
        if not osm_gates:
            osm_gates = None
except Exception:
    pass
```

Pass `osm_gates` as 4th arg to subprocess.

### In `_run_engine_subprocess`:

```python
def _run_engine_subprocess(airport_icao: str, output_path: str, osm_runway: dict | None = None, osm_gates: dict | None = None) -> None:
    ...
    # After osm_runway patch, before engine init:
    if osm_gates:
        import src.ingestion.fallback as _fb
        _fb._loaded_gates = osm_gates
```

This bypasses `get_gates()` entirely — it checks `_loaded_gates` first and returns immediately if set.

## Why not pass taxiway graph?

The taxiway graph (`TaxiwayGraph` object) contains networkx graph + spatial index — complex to pickle. The geometry-derived fallback routing in `_build_arrival_taxi_route()` produces reasonable paths from runway → parallel taxiway → gate as long as gate positions are correct. Cost/benefit doesn't justify the complexity.

## Files to modify

- `app/backend/services/demo_simulation_service.py` — both functions

## Verification

1. `uv run pytest tests/ingestion/test_approach_direction.py -v` — existing tests still pass
2. Deploy → switch KSFO→ATH → aircraft should taxi to gate without jumping off-runway
3. Quick local test: generate demo for ATH, check that gate positions in output are real ATH gates (ref names like "A1"-"A26", "B1"-"B28") not synthetic (generic "A1"-"A10", "B1"-"B10")
