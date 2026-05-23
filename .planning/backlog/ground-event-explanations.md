---
status: backlog
area: simulation, assistant
priority: medium
related:
  - .planning/features/llm-assistant.md
---

# Ground Event Explanations in Observable Data

## Problem

The `/api/assistant/explain` endpoint sends a simulation event (e.g. go-around) to the LLM with a prompt that says "explain the likely cause." The event data only contains `{callsign, icao24, attempt, reason}`, so the LLM invents plausible aviation reasoning (ATC vectoring, tailwind, late configuration) that isn't backed by any actual data fields.

## Goal

Explanations grounded only in observable facts. Two changes needed:
1. Enrich the event payload at recording time with all data that IS available (altitude, speed, vertical_rate, aircraft_type, weather, wind)
2. Rewrite the EXPLAIN_PROMPT to constrain the LLM to only reference provided fields — no speculation

## Changes

### 1. Enrich go-around event data (`src/simulation/engine.py`)

Both go-around recording sites (lines ~1181 and ~1201) currently pass minimal metadata. Add available state and weather fields:

**Weather-triggered go-around (line ~1181):**
```python
{"callsign": state.callsign, "icao24": icao24,
 "attempt": state.go_around_count, "weather": self.capacity.current_category,
 "altitude_ft": round(state.altitude),
 "speed_kts": round(state.velocity),
 "vertical_rate_fpm": round(state.vertical_rate),
 "aircraft_type": state.aircraft_type,
 "wind_direction": self.capacity._wind_direction,
 "wind_gusts_kt": getattr(self.capacity, '_wind_gusts_kt', None),
 "weather_multiplier": round(self.capacity.weather_multiplier, 2)},
```

**High-altitude go-around (line ~1201):**
```python
{"callsign": state.callsign, "icao24": icao24,
 "attempt": state.go_around_count, "reason": "high_altitude",
 "altitude_ft": round(state.altitude),
 "speed_kts": round(state.velocity),
 "vertical_rate_fpm": round(state.vertical_rate),
 "aircraft_type": state.aircraft_type,
 "weather_category": self.capacity.current_category,
 "wind_direction": self.capacity._wind_direction,
 "wind_gusts_kt": getattr(self.capacity, '_wind_gusts_kt', None)},
```

### 2. Rewrite EXPLAIN_PROMPT (`app/backend/api/assistant.py`, line 31)

Replace with prompt enforcing grounding:

```python
EXPLAIN_PROMPT = os.getenv("EXPLAIN_PROMPT", (
    "You are an aviation operations analyst explaining a simulation event. "
    "You MUST only reference data fields present in the event JSON below. "
    "Do NOT speculate about causes not evidenced by the data (e.g., do not mention ATC vectoring, "
    "pilot decisions, or conditions unless a corresponding field exists in the event). "
    "Structure your response as:\n"
    "**Event Analysis:** 2-3 sentences describing what happened, citing specific field values.\n"
    "**Likely Causes:** Only causes directly supported by the event fields. "
    "For example, if reason='high_altitude' and altitude_ft=3800, state that the aircraft was "
    "above the stabilized approach threshold. If weather_category or wind fields are present, "
    "reference those. If no field supports a cause, say 'No additional causal data recorded.'\n"
    "**Operational Impact:** Brief impact statement grounded in the event data.\n"
    "Use aviation terminology. Be concise. Do not use markdown headers beyond the bold labels above."
))
```

### 3. Enrich diversion events (line ~1294)

```python
{"callsign": state.callsign, "icao24": icao24, "alternate": alt_name,
 "reason": "runway_closure" if not self.capacity.active_runways else "go_around_limit",
 "altitude_ft": round(state.altitude),
 "speed_kts": round(state.velocity),
 "aircraft_type": state.aircraft_type,
 "go_around_count": state.go_around_count},
```

## Files Modified

| File | Change |
|------|--------|
| `src/simulation/engine.py` | Enrich go-around + diversion event metadata with state/weather fields |
| `app/backend/api/assistant.py` | Rewrite EXPLAIN_PROMPT to enforce data-grounded explanations |

## Verification

```bash
# Python tests
uv run pytest tests/ -k "go_around or scenario_event or report" -v

# Run quick local sim, check enriched fields in output
uv run python -m src.simulation.cli --airport SFO --arrivals 30 --departures 30 --seed 42

# Inspect output JSON for go-around events — should have altitude_ft, speed_kts, etc.
# Test explain endpoint — LLM response should only reference fields present in the event
```
