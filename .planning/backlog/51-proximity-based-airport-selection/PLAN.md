# Fix: Proximity-based fallback for origin/destination airport selection

## Context

When no calibration profile exists for an airport, `_pick_random_airport()` in `fallback.py:2218-2223` falls back to US-centric hardcoded lists (`DOMESTIC_AIRPORTS` = 20 US airports, `INTERNATIONAL_AIRPORTS` = 10 global hubs). This means a European airport like LSGG (Geneva) gets random US domestic airports as origins/destinations, which is unrealistic.

The same issue exists in `schedule_generator.py:289-292` (`_select_destination_unchecked` fallback).

**Goal:** When no calibrated profile exists, pick 70% "nearby" airports (same country or within 3000km) and 30% international airports (beyond 3000km).

## Approach

Use `AIRPORT_COORDINATES` (already exists in `schedule_generator.py:125-163`) to compute haversine distance from the current airport to all known airports, then split into nearby (<= 3000km) vs far (> 3000km).

---

## Changes

### 1. `src/ingestion/schedule_generator.py`

**Add `_haversine_km()` helper** (~after line 100, near existing coordinate data):

```python
def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
```

**Add `get_nearby_airports()` function:**

```python
def get_nearby_airports(
    iata: str, max_distance_km: float = 3000.0,
    ref_lat: float | None = None, ref_lon: float | None = None,
) -> tuple[list[str], list[str]]:
    """Split known airports into nearby (<= max_distance_km) and far (> max_distance_km).
    Returns (nearby, far), both excluding the given airport.
    Uses AIRPORT_COORDINATES for the reference point, falling back to ref_lat/ref_lon.
    Same-country airports (from COUNTRY_DOMESTIC_AIRPORTS) are always included in nearby.
    """
```

Logic:
1. Look up `iata` in `AIRPORT_COORDINATES` for reference coords; fall back to `ref_lat/ref_lon`
2. For every airport in `AIRPORT_COORDINATES` (excluding `iata`), compute distance
3. Also include same-country airports from `COUNTRY_DOMESTIC_AIRPORTS` as nearby
4. Return `(nearby, far)`

**Expand `AIRPORT_COORDINATES`** — add missing airports from `COUNTRY_DOMESTIC_AIRPORTS` and key European airports so distance computation has good coverage. Add ~30 airports:

```python
# European (from COUNTRY_DOMESTIC_AIRPORTS + well-known)
"GVA": (46.2381, 6.1089),    # Geneva
"ATH": (37.9364, 23.9445),   # Athens
"MUC": (48.3538, 11.7861), "DUS": (51.2895, 6.7668),
"HAM": (53.6304, 9.9882), "BER": (52.3667, 13.5033),
"STR": (48.6899, 9.2220), "CGN": (50.8659, 7.1427),
"ORY": (48.7233, 2.3794), "NCE": (43.6584, 7.2159),
"LYS": (45.7256, 5.0811), "MRS": (43.4393, 5.2214),
"TLS": (43.6291, 1.3638), "BOD": (44.8283, -0.7153),
"LGW": (51.1537, -0.1821), "MAN": (53.3537, -2.2750),
"EDI": (55.9508, -3.3615), "STN": (51.8850, 0.2350),
"EIN": (51.4501, 5.3743), "RTM": (51.9569, 4.4372),
# Asia-Pacific
"KIX": (34.4347, 135.2440), "FUK": (33.5859, 130.4507),
"CTS": (42.7752, 141.6925), "GMP": (37.5583, 126.7906),
"PUS": (35.1795, 128.9382), "CJU": (33.5104, 126.4929),
# Americas (additional)
"GIG": (-22.8090, -43.2506), "CGH": (-23.6261, -46.6564),
"MEL": (-37.6733, 144.8433), "BNE": (-27.3842, 153.1175),
"YYZ": (43.6777, -79.6248), "YVR": (49.1947, -123.1790),
"MEX": (19.4363, -99.0721), "CUN": (21.0365, -86.8771),
# Middle East / Africa
"AUH": (24.4330, 54.6511), "DOH": (25.2731, 51.6081),
"IST": (41.2753, 28.7519),
"CMN": (33.3675, -7.5898), "CAI": (30.1219, 31.4056),
```

**Update `_select_destination_unchecked()` fallback** (line 289-292):

```python
# Before:
if random.random() < 0.7:
    return random.choice(DOMESTIC_AIRPORTS)
return random.choice(INTERNATIONAL_AIRPORTS)

# After:
nearby, far = get_nearby_airports(airport or "SFO")
if random.random() < 0.7 and nearby:
    return random.choice(nearby)
if far:
    return random.choice(far)
return random.choice(INTERNATIONAL_AIRPORTS)
```

### 2. `src/ingestion/fallback.py`

**Update `_pick_random_airport()` fallback** (line 2218-2223):

```python
# Before:
from src.ingestion.schedule_generator import DOMESTIC_AIRPORTS, INTERNATIONAL_AIRPORTS
if random.random() < 0.7:
    pool = [a for a in DOMESTIC_AIRPORTS if a != exclude] or DOMESTIC_AIRPORTS
else:
    pool = [a for a in INTERNATIONAL_AIRPORTS if a != exclude] or INTERNATIONAL_AIRPORTS
return random.choice(pool)

# After:
from src.ingestion.schedule_generator import get_nearby_airports, INTERNATIONAL_AIRPORTS
local_iata = get_current_airport_iata()
nearby, far = get_nearby_airports(local_iata)
if random.random() < 0.7:
    pool = [a for a in nearby if a != exclude]
else:
    pool = [a for a in far if a != exclude]
if not pool:
    pool = [a for a in INTERNATIONAL_AIRPORTS if a != exclude] or INTERNATIONAL_AIRPORTS
return random.choice(pool)
```

**Update `_AIRPORT_COUNTRY`** (line 2172) — add entries for the new airports (GVA, ATH, MUC, etc.) so `_get_origin_country()` returns correct values.

---

## Files to modify

| File | Changes |
|------|---------|
| `src/ingestion/schedule_generator.py` | Add `_haversine_km()`, `get_nearby_airports()`, expand `AIRPORT_COORDINATES`, update `_select_destination_unchecked` fallback |
| `src/ingestion/fallback.py` | Update `_pick_random_airport()` fallback, expand `_AIRPORT_COUNTRY` |

---

## Verification

1. `uv run pytest tests/ -k "pick_random or select_destination or fallback or schedule" -v` — existing tests
2. `uv run pytest tests/ -v` — full suite
3. Manual: set airport to LSGG, verify generated flights show European airports (CDG, FRA, AMS, LHR, MUC, etc.) ~70% of the time as origins/destinations
