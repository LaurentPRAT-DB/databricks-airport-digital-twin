import { FeatureCollection, Feature, Polygon, LineString, Point } from 'geojson';

// Airport center coordinates (SFO - San Francisco International Airport)
export const AIRPORT_CENTER: [number, number] = [37.6213, -122.379];

// Zoom level for initial view
export const DEFAULT_ZOOM = 14;

// ============================================================================
// SEPARATION CONSTRAINTS (FAA/ICAO Standards)
// These match the backend fallback.py constants
// ============================================================================

// Wake turbulence categories
export const WAKE_CATEGORIES = {
  SUPER: ['A380'],
  HEAVY: ['B747', 'B777', 'B787', 'A330', 'A340', 'A350', 'A345'],
  LARGE: ['A320', 'A321', 'A319', 'A318', 'B737', 'B738', 'B739'],
  SMALL: ['CRJ9', 'E175', 'E190'],
} as const;

// Minimum separation in nautical miles (lead → follow)
export const WAKE_SEPARATION_NM: Record<string, number> = {
  'SUPER_SUPER': 4.0,
  'SUPER_HEAVY': 6.0,
  'SUPER_LARGE': 7.0,
  'SUPER_SMALL': 8.0,
  'HEAVY_HEAVY': 4.0,
  'HEAVY_LARGE': 5.0,
  'HEAVY_SMALL': 6.0,
  'LARGE_LARGE': 3.0,
  'LARGE_SMALL': 4.0,
  'SMALL_SMALL': 3.0,
};
export const DEFAULT_SEPARATION_NM = 3.0;

// Convert NM to degrees (1 NM ≈ 1/60 degree)
export const NM_TO_DEG = 1.0 / 60.0;

// Separation distances in degrees
export const MIN_APPROACH_SEPARATION_DEG = 3.0 * NM_TO_DEG;  // 3 NM minimum
export const MIN_TAXI_SEPARATION_DEG = 0.001;  // ~100m / ~330ft
export const MIN_GATE_SEPARATION_DEG = 0.002;  // ~200m

// Capacity limits
export const MAX_APPROACH_AIRCRAFT = 4;
export const MAX_PARKED_AIRCRAFT = 5;  // Number of gates
export const MAX_TAXI_AIRCRAFT = 2;

// Gate definitions (matching backend fallback.py) - Real SFO terminal positions
// Gates spread across International Terminal (G, A) and Domestic Terminals (B, C)
export const GATE_POSITIONS: Record<string, [number, number]> = {
  // International Terminal - Boarding Area G
  'G1': [37.6145, -122.3955],  // Wide-body capable
  'G2': [37.6140, -122.3945],
  'G3': [37.6135, -122.3935],
  // International Terminal - Boarding Area A
  'A1': [37.6155, -122.3900],  // Wide-body capable
  'A2': [37.6150, -122.3890],
  // Domestic Terminal 1
  'B1': [37.6165, -122.3850],
  'B2': [37.6160, -122.3840],
  // Domestic Terminal 2/3
  'C1': [37.6175, -122.3800],
  'C2': [37.6170, -122.3790],
};

// GeoJSON FeatureCollection for airport layout - Real SFO from FAA data
export const airportLayout: FeatureCollection = {
  type: 'FeatureCollection',
  features: [
    // Runway 28R/10L - 11,870 ft (north parallel, extends into bay)
    {
      type: 'Feature',
      properties: {
        type: 'runway',
        name: '28R/10L',
        length: 11870,
        width: 200,
      },
      geometry: {
        type: 'Polygon',
        coordinates: [[
          [-122.393392, 37.629739],  // 10L threshold + offset
          [-122.357141, 37.614534],  // 28R threshold + offset
          [-122.357141, 37.612534],  // 28R threshold - offset
          [-122.393392, 37.627739],  // 10L threshold - offset
          [-122.393392, 37.629739],
        ]],
      },
    } as Feature<Polygon>,

    // Runway 28L/10R - 11,381 ft (south parallel, extends into bay)
    {
      type: 'Feature',
      properties: {
        type: 'runway',
        name: '28L/10R',
        length: 11381,
        width: 200,
      },
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
    } as Feature<Polygon>,

    // Runway 01R/19L - 8,650 ft (east crosswind)
    {
      type: 'Feature',
      properties: {
        type: 'runway',
        name: '01R/19L',
        length: 8650,
        width: 200,
      },
      geometry: {
        type: 'Polygon',
        coordinates: [[
          [-122.380041, 37.606330],  // 01R threshold - offset
          [-122.366111, 37.627342],  // 19L threshold - offset
          [-122.368111, 37.627342],  // 19L threshold + offset
          [-122.382041, 37.606330],  // 01R threshold + offset
          [-122.380041, 37.606330],
        ]],
      },
    } as Feature<Polygon>,

    // Runway 01L/19R - 7,650 ft (west crosswind)
    {
      type: 'Feature',
      properties: {
        type: 'runway',
        name: '01L/19R',
        length: 7650,
        width: 200,
      },
      geometry: {
        type: 'Polygon',
        coordinates: [[
          [-122.381929, 37.607898],  // 01L threshold - offset
          [-122.369609, 37.626481],  // 19R threshold - offset
          [-122.371609, 37.626481],  // 19R threshold + offset
          [-122.383929, 37.607898],  // 01L threshold + offset
          [-122.381929, 37.607898],
        ]],
      },
    } as Feature<Polygon>,

    // Taxiway connecting terminals to runways
    {
      type: 'Feature',
      properties: {
        type: 'taxiway',
        name: 'Alpha',
      },
      geometry: {
        type: 'LineString',
        coordinates: [
          [-122.390, 37.615],
          [-122.385, 37.618],
          [-122.380, 37.622],
        ],
      },
    } as Feature<LineString>,

    // Taxiway Bravo
    {
      type: 'Feature',
      properties: {
        type: 'taxiway',
        name: 'Bravo',
      },
      geometry: {
        type: 'LineString',
        coordinates: [
          [-122.385, 37.615],
          [-122.380, 37.618],
          [-122.375, 37.622],
        ],
      },
    } as Feature<LineString>,

    // Taxiway connecting to crosswind runways
    {
      type: 'Feature',
      properties: {
        type: 'taxiway',
        name: 'Charlie',
      },
      geometry: {
        type: 'LineString',
        coordinates: [
          [-122.383, 37.610],
          [-122.380, 37.615],
          [-122.378, 37.620],
        ],
      },
    } as Feature<LineString>,

    // Gates (5 total, matching backend separation constraints)
    // Gate spacing: 0.008 deg = ~800m to allow for aircraft + ground equipment
    ...Object.entries(GATE_POSITIONS).map(([name, coords]): Feature<Point> => ({
      type: 'Feature',
      properties: {
        type: 'gate',
        name,
        terminal: name.charAt(0),  // 'A' or 'B'
        // Capacity info for UI
        widebody: name === 'A1' || name === 'B2',  // End gates can handle wide-body
      },
      geometry: {
        type: 'Point',
        coordinates: [coords[1], coords[0]],  // GeoJSON uses [lon, lat]
      },
    })),
  ],
};

// Helper function to get features by type
export function getFeaturesByType(type: string): Feature[] {
  return airportLayout.features.filter(
    (feature) => feature.properties?.type === type
  );
}

// ============================================================================
// SEPARATION HELPER FUNCTIONS
// ============================================================================

/**
 * Get wake turbulence category for an aircraft type
 */
export function getWakeCategory(aircraftType: string): 'SUPER' | 'HEAVY' | 'LARGE' | 'SMALL' {
  if (WAKE_CATEGORIES.SUPER.includes(aircraftType as never)) return 'SUPER';
  if (WAKE_CATEGORIES.HEAVY.includes(aircraftType as never)) return 'HEAVY';
  if (WAKE_CATEGORIES.SMALL.includes(aircraftType as never)) return 'SMALL';
  return 'LARGE';  // Default for unknown types
}

/**
 * Get required separation in nautical miles between two aircraft types
 * @param leadType Aircraft type of the lead (ahead) aircraft
 * @param followType Aircraft type of the following aircraft
 */
export function getRequiredSeparationNM(leadType: string, followType: string): number {
  const leadCat = getWakeCategory(leadType);
  const followCat = getWakeCategory(followType);
  const key = `${leadCat}_${followCat}`;
  return WAKE_SEPARATION_NM[key] ?? DEFAULT_SEPARATION_NM;
}

/**
 * Get required separation in degrees between two aircraft types
 */
export function getRequiredSeparationDeg(leadType: string, followType: string): number {
  return getRequiredSeparationNM(leadType, followType) * NM_TO_DEG;
}

/**
 * Calculate distance in nautical miles between two lat/lon positions
 */
export function distanceNM(
  pos1: [number, number],  // [lat, lon]
  pos2: [number, number]
): number {
  const latDiff = pos1[0] - pos2[0];
  const lonDiff = pos1[1] - pos2[1];
  const degDist = Math.sqrt(latDiff * latDiff + lonDiff * lonDiff);
  return degDist / NM_TO_DEG;
}

/**
 * Check if two positions have sufficient approach separation
 */
export function hasApproachSeparation(
  leadPos: [number, number],
  leadType: string,
  followPos: [number, number],
  followType: string
): boolean {
  const requiredNM = getRequiredSeparationNM(leadType, followType);
  const actualNM = distanceNM(leadPos, followPos);
  return actualNM >= requiredNM;
}

/**
 * Get separation status for UI display
 */
export function getSeparationStatus(
  actualNM: number,
  requiredNM: number
): 'ok' | 'warning' | 'violation' {
  if (actualNM >= requiredNM * 1.2) return 'ok';        // 20%+ buffer
  if (actualNM >= requiredNM) return 'warning';         // At minimum
  return 'violation';                                    // Below minimum
}
