# Phase 13: Airport Pre-load, New Airports, and Cache Status

## Context

When switching airports, data is fetched from OSM Overpass API if not already cached in the lakehouse (3-tier: Lakebase < UC tables < OSM). This works but the first load for each airport is slow. There's no way to bulk pre-load all dropdown airports, no visibility into which are cached, and the dropdown is missing notable airports.

All 12 current airports are confirmed available on OSM Overpass API (tested 2026-03-11).

---

## Plan — 3 Files Modified, 0 New Files

### 1. Backend: Add pre-load endpoint (`app/backend/api/routes.py`)

Add `POST /airports/preload` endpoint near the existing persistence routes (after line ~693):

```python
@router.post("/airports/preload", tags=["airport"])
async def preload_airports(
    icao_codes: list[str] = Body(default=None, description="ICAO codes to preload. If null, preloads all well-known airports"),
) -> dict:
```

**Logic:**
- If `icao_codes` is null/empty, use the `WELL_KNOWN_AIRPORTS` list (same list as frontend dropdown — define it once in the backend)
- For each airport not already in lakehouse (`service.list_persisted_airports()`), call `service.initialize_from_lakehouse(icao, fallback_to_osm=True)`
- Return `{"preloaded": [...], "already_cached": [...], "failed": [...]}`
- Process sequentially (Overpass API rate limits)
- Broadcast progress via WebSocket for each airport

Also add a constant at module level with the well-known airports list:

```python
WELL_KNOWN_AIRPORTS = [
    "KSFO", "KJFK", "KLAX", "KORD", "KATL",  # US
    "EGLL", "LFPG",                              # Europe
    "OMAA", "OMDB",                              # Middle East
    "RJTT", "VHHH", "WSSS",                      # Asia-Pacific
    # New additions
    "KDFW", "KDEN", "KMIA", "KSEA",              # US
    "EHAM", "EDDF", "LEMD", "LIRF",              # Europe
    "ZBAA", "RKSI", "VTBS",                       # Asia-Pacific
    "FAOR", "GMMN",                               # Africa
    "SBGR", "MMMX",                               # Americas
]
```

Also add `GET /airports/preload/status` to check which airports are cached:

```python
@router.get("/airports/preload/status", tags=["airport"])
async def preload_status() -> dict:
```

Returns `{ airports: [{icao, name, cached: bool}, ...] }` by comparing `WELL_KNOWN_AIRPORTS` against `list_persisted_airports()`.

### 2. Frontend: Show cache status in dropdown (`app/frontend/src/components/AirportSelector/AirportSelector.tsx`)

Changes to `AirportSelector.tsx`:

- Expand `WELL_KNOWN_AIRPORTS` with the same new airports added on the backend (KDFW, KDEN, KMIA, KSEA, EHAM, EDDF, LEMD, LIRF, ZBAA, RKSI, VTBS, FAOR, GMMN, SBGR, MMMX)
- Group airports by region with section headers in dropdown (Americas, Europe, Middle East, Asia-Pacific, Africa)
- On dropdown open, fetch `GET /airports/preload/status` and show a green dot next to cached airports, gray dot next to uncached ones
- Add a "Pre-load All" button at the bottom of the dropdown that calls `POST /airports/preload` and shows progress

Add to the component:

```typescript
const [cacheStatus, setCacheStatus] = useState<Record<string, boolean>>({});
const [preloading, setPreloading] = useState(false);
```

On dropdown open → `fetch('/api/airports/preload/status')` → update `cacheStatus`.

Each airport entry shows:
- Green circle = cached (fast switch)
- Gray circle = not cached (will fetch from OSM)

"Pre-load All" button at bottom:
- Calls `POST /api/airports/preload`
- Shows spinner while running
- Refreshes cache status on completion

### 3. Backend: Add well-known airport metadata (`app/backend/api/routes.py`)

The `WELL_KNOWN_AIRPORTS` backend constant includes enough metadata for the status endpoint:

```python
WELL_KNOWN_AIRPORT_INFO = {
    "KSFO": {"iata": "SFO", "name": "San Francisco International", "city": "San Francisco, CA", "region": "Americas"},
    "KJFK": {"iata": "JFK", "name": "John F. Kennedy International", "city": "New York, NY", "region": "Americas"},
    # ... all airports with region tags
}
```

This avoids duplicating the list between frontend and backend — the frontend can fetch airport info from the status endpoint.

---

## New Airports Being Added (15)

| ICAO | IATA | Name | City | Region |
|------|------|------|------|--------|
| KDFW | DFW | Dallas/Fort Worth International | Dallas, TX | Americas |
| KDEN | DEN | Denver International | Denver, CO | Americas |
| KMIA | MIA | Miami International | Miami, FL | Americas |
| KSEA | SEA | Seattle-Tacoma International | Seattle, WA | Americas |
| EHAM | AMS | Amsterdam Schiphol | Amsterdam, NL | Europe |
| EDDF | FRA | Frankfurt Airport | Frankfurt, DE | Europe |
| LEMD | MAD | Adolfo Suarez Madrid-Barajas | Madrid, ES | Europe |
| LIRF | FCO | Leonardo da Vinci (Fiumicino) | Rome, IT | Europe |
| ZBAA | PEK | Beijing Capital International | Beijing, CN | Asia-Pacific |
| RKSI | ICN | Incheon International | Seoul, KR | Asia-Pacific |
| VTBS | BKK | Suvarnabhumi Airport | Bangkok, TH | Asia-Pacific |
| FAOR | JNB | O.R. Tambo International | Johannesburg, ZA | Africa |
| GMMN | CMN | Mohammed V International | Casablanca, MA | Africa |
| SBGR | GRU | Guarulhos International | Sao Paulo, BR | Americas |
| MMMX | MEX | Mexico City International | Mexico City, MX | Americas |

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Sequential pre-load (not parallel) | Overpass API rate limits; parallel requests get 429s |
| Backend holds airport list | Single source of truth; frontend fetches from status endpoint |
| Region grouping in dropdown | Better UX with 27 airports; easy to find by geography |
| Cache status on dropdown open | Lightweight fetch; no polling needed |
| No new files | Fits naturally into existing routes.py and AirportSelector.tsx |
