# Configurable Gate Time Multiplier — UI + API

## Context

The consistent `DEMO_GATE_TIME_MULTIPLIER` is now applied across all gate-wait code paths (fallback.py, gse_model.py, gse_service.py). The user wants this value **visible on the UI**
and **adjustable at runtime**, with safety against illogical values (0, negative, huge).

## Changes

### 1. `src/ingestion/fallback.py` — Mutable multiplier with getter/setter

Replace the module-level constant with a mutable variable + getter/setter. All 6 existing call sites use `get_gate_time_multiplier()`.

```python
_DEFAULT_GATE_TIME_MULTIPLIER = 8.0
_gate_time_multiplier = _DEFAULT_GATE_TIME_MULTIPLIER

def get_gate_time_multiplier() -> float:
    return _gate_time_multiplier

def set_gate_time_multiplier(value: float) -> float:
    global _gate_time_multiplier
    _gate_time_multiplier = max(1.0, min(60.0, float(value)))
    return _gate_time_multiplier
```

- Clamped range: **1x** (real-time) to **60x** (max compression)
- `float()` cast handles string/int inputs
- Returns the clamped value so caller knows what was actually set

Update all 6 references: `DEMO_GATE_TIME_MULTIPLIER` -> `get_gate_time_multiplier()`.

### 2. `src/ml/gse_model.py` + `app/backend/services/gse_service.py`

Change imports from `DEMO_GATE_TIME_MULTIPLIER` to `get_gate_time_multiplier` and call it.

### 3. `app/backend/api/routes.py` — GET + PUT endpoints

```
GET  /api/settings/gate-time-multiplier  →  {"multiplier": 8.0, "min": 1, "max": 60, "default": 8}
PUT  /api/settings/gate-time-multiplier  →  body: {"multiplier": 12}  →  {"multiplier": 12.0}
```

PUT clamps the value and returns the clamped result.

### 4. `app/frontend/src/components/Header/Header.tsx` — Speed chip + dropdown

Add a small clickable chip in the header (next to the "Demo" badge) showing the current multiplier. On click, show a dropdown with preset buttons: **1x, 4x, 8x, 16x, 32x**.

- Fetch current value on mount via `GET /api/settings/gate-time-multiplier`
- Update via `PUT /api/settings/gate-time-multiplier` on button click
- Lightning-bolt icon + "8x" text
- Close dropdown on outside click or selection

### 5. Tests

Update `tests/test_synthetic_data_requirements.py::TestTurnaroundStatus` to import getter. Default is still 8.0 so test values don't change.

## Files Modified

| File | Changes |
|---|---|
| `src/ingestion/fallback.py` | Constant → getter/setter, update 6 call sites |
| `src/ml/gse_model.py` | Import getter instead of constant |
| `app/backend/services/gse_service.py` | Import getter instead of constant |
| `app/backend/api/routes.py` | Add GET/PUT `/settings/gate-time-multiplier` |
| `app/frontend/src/components/Header/Header.tsx` | Speed chip + preset dropdown |

## Safety

- **Clamped range**: 1.0 – 60.0 (prevents 0, negative, absurd values)
- **No persistence**: Resets to 8.0 on server restart (intentional — demo control)
- **Type coercion**: `float()` + clamp in setter handles bad inputs gracefully

## Verification

1. `uv run pytest tests/ -v` — all pass
2. `cd app/frontend && npm test -- --run` — all pass
3. Local dev: chip visible in header, dropdown works, turnaround speed changes on next cycle

## Status: NOT YET IMPLEMENTED
