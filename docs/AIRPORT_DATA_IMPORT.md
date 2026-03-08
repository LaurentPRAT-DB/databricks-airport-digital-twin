# Airport Data Import Guide

This document describes the process for importing real airport data (runways, taxiways, terminals, gates) to use in the Airport Digital Twin visualization.

## Overview

The digital twin can use real airport layout data from FAA/ICAO sources. This guide covers importing data for any airport by:
1. Obtaining FAA runway and airport data
2. Converting coordinates to visualization formats
3. Updating frontend and backend configurations

## Data Sources

### FAA AirNav (US Airports)
- **URL**: https://www.airnav.com/airport/{ICAO_CODE}
- **Data**: Runway coordinates, dimensions, headings, frequencies
- **Example**: https://www.airnav.com/airport/KSFO (San Francisco)

### FAA NASR Database
- **URL**: https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/
- **Data**: Official runway endpoints, dimensions, surfaces
- **Format**: CSV/XML downloads

### OpenStreetMap
- **URL**: https://www.openstreetmap.org
- **Data**: Terminal outlines, taxiways, aprons (community-contributed)

## Step-by-Step Import Process

### Step 1: Gather Airport Data

For each airport, collect:

| Data Point | Source | Example (SFO) |
|------------|--------|---------------|
| ICAO Code | FAA | KSFO |
| Airport Reference Point (ARP) | FAA | 37.6213, -122.379 |
| Runway Endpoints | AirNav | See below |
| Runway Dimensions | AirNav | Length, width |
| Terminal Positions | OSM | Approximate lat/lon |
| Gate Locations | Manual | Terminal area coords |

**Runway Data Format** (from FAA):
```
Runway 28L/10R:
  28L Threshold: 37.612712, -122.358349
  10R Threshold: 37.627291, -122.393105
  Length: 11,381 ft
  Width: 200 ft
  Heading: 298°/118°
```

### Step 2: Define Coordinate System

Set the airport center as the origin for 3D coordinates:

```typescript
// In map3d-calculations.ts
export const DEFAULT_CENTER_LAT = 37.6213;  // Airport Reference Point
export const DEFAULT_CENTER_LON = -122.379;
export const SCALE = 10000;  // 1 degree ≈ 10000 scene units
```

### Step 3: Convert Coordinates

Use the `latLonTo3D` function to convert real-world coordinates:

```typescript
function latLonTo3D(lat: number, lon: number, centerLat: number, centerLon: number) {
  const cosLat = Math.cos((centerLat * Math.PI) / 180);
  const x = (lon - centerLon) * SCALE * cosLat;
  const z = (centerLat - lat) * SCALE;
  return { x, y: 0.1, z };
}
```

**Example Conversion (Runway 28L threshold)**:
```
Input: lat=37.612712, lon=-122.358349
Center: lat=37.6213, lon=-122.379
cosLat = 0.7915
x = (-122.358349 - (-122.379)) * 10000 * 0.7915 = 163.6
z = (37.6213 - 37.612712) * 10000 = 85.9
Output: { x: 163.6, y: 0.1, z: 85.9 }
```

### Step 4: Update Configuration Files

#### 4.1 Frontend 3D Config (`app/frontend/src/constants/airport3D.ts`)

```typescript
export const AIRPORT_3D_CONFIG: Airport3DConfig = {
  center: { x: 0, y: 0, z: 0 },
  scale: 0.001,
  runways: [
    {
      id: '28L/10R',
      start: { x: 163.6, y: 0.1, z: 95.9 },   // 28L threshold
      end: { x: -111.7, y: 0.1, z: -49.9 },   // 10R threshold
      width: 61,  // 200 ft ≈ 61m
      color: 0x333333,
    },
    // Add more runways...
  ],
  // ...
};
```

#### 4.2 Frontend 2D Layout (`app/frontend/src/constants/airportLayout.ts`)

```typescript
export const AIRPORT_CENTER: [number, number] = [37.6213, -122.379];

export const airportLayout: FeatureCollection = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature',
      properties: { type: 'runway', name: '28L/10R', length: 11381, width: 200 },
      geometry: {
        type: 'Polygon',
        coordinates: [[
          [-122.393105, 37.627291],  // 10R threshold + offset
          [-122.358349, 37.612712],  // 28L threshold + offset
          [-122.358349, 37.610712],  // 28L threshold - offset
          [-122.393105, 37.625291],  // 10R threshold - offset
          [-122.393105, 37.627291],
        ]],
      },
    },
    // Add more features...
  ],
};
```

#### 4.3 Backend Fallback (`src/ingestion/fallback.py`)

```python
AIRPORT_CENTER = (37.619806, -122.374821)

RUNWAY_ENDPOINTS = {
    "28L": {"start": (37.612712, -122.358349), "end": (37.627291, -122.393105)},
    # Add more runways...
}

GATES = {
    "G1": (37.6145, -122.3955),
    "G2": (37.6140, -122.3945),
    # Add more gates...
}
```

#### 4.4 ML Congestion Model (`src/ml/congestion_model.py`)

```python
def _define_airport_areas(self) -> Dict[str, AirportArea]:
    return {
        "runway_28L_10R": AirportArea(
            area_id="runway_28L_10R",
            area_type="runway",
            capacity=2,
            lat_range=(37.610, 37.628),
            lon_range=(-122.395, -122.355)
        ),
        # Add more areas...
    }
```

### Step 5: Update Tests

After updating coordinates, fix tests that check specific values:

```python
# tests/test_ml.py
def test_congestion_predictor_init(self):
    predictor = CongestionPredictor()
    assert len(predictor.areas) == 7  # Update count
    assert "runway_28L_10R" in predictor.areas  # Update names

# tests/test_aircraft_separation.py
def test_gates_exist(self):
    assert len(GATES) == 9  # Update count
    assert "G1" in GATES  # Update names
```

### Step 6: Validate and Deploy

```bash
# Run tests
uv run pytest tests/ -v

# Run frontend tests
cd app/frontend && npm test -- --run

# Build and deploy
npm run build
cd ../..
databricks bundle deploy --target dev
databricks apps deploy airport-digital-twin-dev \
  --source-code-path /Workspace/Users/{user}/.bundle/airport-digital-twin/dev/files
```

## Airport-Specific Examples

### SFO (San Francisco International)
- ICAO: KSFO
- Runways: 4 (28L/10R, 28R/10L, 01L/19R, 01R/19L)
- Configuration: Parallel + crosswind layout
- Reference: This repo's current configuration

### LAX (Los Angeles International)
- ICAO: KLAX
- Runways: 4 (24L/06R, 24R/06L, 25L/07R, 25R/07L)
- Configuration: North and South parallel complexes
- ARP: 33.9425, -118.408

### JFK (John F. Kennedy International)
- ICAO: KJFK
- Runways: 4 (04L/22R, 04R/22L, 13L/31R, 13R/31L)
- Configuration: Two crossing pairs
- ARP: 40.6398, -73.7789

## Automation Options

### FAA Data Fetcher Script

```python
import requests
from bs4 import BeautifulSoup

def fetch_runway_data(icao_code: str) -> dict:
    """Fetch runway data from AirNav."""
    url = f"https://www.airnav.com/airport/{icao_code}"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    # Parse runway table
    runways = []
    # ... parsing logic ...

    return {
        "icao": icao_code,
        "runways": runways,
        "reference_point": extract_arp(soup)
    }
```

### AIXM Import API

The backend supports AIXM format import via API:

```bash
curl -X POST http://localhost:8000/api/airport/import/aixm \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/airport.aixm", "merge_existing": false}'
```

## Troubleshooting

### Common Issues

1. **Runways appear rotated**: Check that the heading matches FAA data and coordinates are entered in correct order (threshold 1 → threshold 2).

2. **Scale mismatch between 2D/3D**: Ensure `SCALE` constant is consistent (default: 10000).

3. **Aircraft outside airport bounds**: Verify `AIRPORT_CENTER` matches between frontend and backend.

4. **Gates don't align with terminal**: Gate positions should be offset ~50m from terminal building centerline.

### Validation Checklist

- [ ] Airport center coordinates match FAA ARP
- [ ] Runway endpoints match FAA threshold coordinates
- [ ] Runway widths converted from feet to meters (÷ 3.28)
- [ ] Terminal and gate positions are within airport bounds
- [ ] ML congestion areas cover all runways and aprons
- [ ] Tests updated for new area counts and names
