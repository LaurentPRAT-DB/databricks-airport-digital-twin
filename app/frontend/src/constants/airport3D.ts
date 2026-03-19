/**
 * 3D Airport Configuration
 *
 * Defines coordinates, dimensions, and colors for 3D visualization
 * of the airport digital twin.
 */

import { BuildingPlacement } from '../config/buildingModels';

export interface Position3D {
  x: number;
  y: number;
  z: number;
}

export interface Dimensions3D {
  width: number;
  height: number;
  depth: number;
}

export interface RunwayConfig {
  id: string;
  start: Position3D;
  end: Position3D;
  width: number;
  color: number;
}

export interface TaxiwayConfig {
  id: string;
  points: Position3D[];
  width: number;
  color: number;
}

export interface GroundConfig {
  size: number;
  color: number;
}

export interface LightingConfig {
  ambient: {
    intensity: number;
  };
  directional: {
    position: Position3D;
    intensity: number;
  };
}

export interface Airport3DConfig {
  center: Position3D;
  scale: number;
  runways: RunwayConfig[];
  taxiways: TaxiwayConfig[];
  buildings: BuildingPlacement[];
  ground: GroundConfig;
  lighting: LightingConfig;
}

export const AIRPORT_3D_CONFIG: Airport3DConfig = {
  // Scene center (origin)
  center: { x: 0, y: 0, z: 0 },

  // Scale factor: convert meters to scene units
  scale: 0.001,

  // Runway configurations - Real SFO 4-runway layout from FAA data
  // Coordinates converted from lat/lon using latLonTo3D transformation
  runways: [
    {
      // Runway 28L/10R - 11,381 ft, heading 298°/118° (south parallel)
      id: '28L/10R',
      start: { x: 163.6, y: 0.1, z: 95.9 },   // 28L threshold (west)
      end: { x: -111.7, y: 0.1, z: -49.9 },   // 10R threshold (east)
      width: 61,  // 200 ft = ~61m
      color: 0x333333,
    },
    {
      // Runway 28R/10L - 11,870 ft, heading 298°/118° (north parallel)
      id: '28R/10L',
      start: { x: 173.1, y: 0.1, z: 77.7 },   // 28R threshold (west)
      end: { x: -114.0, y: 0.1, z: -74.4 },   // 10L threshold (east)
      width: 61,
      color: 0x333333,
    },
    {
      // Runway 01L/19R - 7,650 ft, heading 028°/208° (west crosswind)
      id: '01L/19R',
      start: { x: -31.1, y: 0.1, z: 134.0 },  // 01L threshold (south)
      end: { x: 66.5, y: 0.1, z: -51.8 },     // 19R threshold (north)
      width: 61,
      color: 0x333333,
    },
    {
      // Runway 01R/19L - 8,650 ft, heading 028°/208° (east crosswind)
      id: '01R/19L',
      start: { x: -16.2, y: 0.1, z: 149.7 },  // 01R threshold (south)
      end: { x: 94.2, y: 0.1, z: -60.4 },     // 19L threshold (north)
      width: 61,
      color: 0x333333,
    },
  ],

  // Taxiway configurations - simplified main taxiways
  taxiways: [
    {
      // Taxiway connecting 28L/10R to terminal
      id: 'A',
      points: [
        { x: 0, y: 0.05, z: 95 },    // Near 28L
        { x: -40, y: 0.05, z: 80 },
        { x: -70, y: 0.05, z: 63 },  // To terminal
      ],
      width: 20,
      color: 0x555555,
    },
    {
      // Taxiway connecting 28R/10L to terminal
      id: 'B',
      points: [
        { x: 0, y: 0.05, z: 77 },    // Near 28R
        { x: -40, y: 0.05, z: 70 },
        { x: -70, y: 0.05, z: 63 },  // To terminal
      ],
      width: 20,
      color: 0x555555,
    },
    {
      // Taxiway connecting crosswind runways
      id: 'C',
      points: [
        { x: -20, y: 0.05, z: 140 },  // Near 01L/01R
        { x: -50, y: 0.05, z: 100 },
        { x: -70, y: 0.05, z: 63 },   // To terminal
      ],
      width: 20,
      color: 0x555555,
    },
  ],

  // Building configurations (GLTF models or procedural fallbacks)
  buildings: [
    // Control Tower - positioned east of the terminal
    {
      id: 'control-tower-1',
      type: 'control-tower',
      position: { x: 150, y: 0, z: 0 },
      rotation: 0,
    },
    // Hangars - north side of airport
    {
      id: 'hangar-1',
      type: 'hangar',
      position: { x: -300, y: 0, z: -250 },
      rotation: Math.PI / 2,
    },
    {
      id: 'hangar-2',
      type: 'hangar',
      position: { x: -150, y: 0, z: -250 },
      rotation: Math.PI / 2,
    },
    // Cargo building - west side
    {
      id: 'cargo-1',
      type: 'cargo',
      position: { x: -350, y: 0, z: 50 },
      rotation: 0,
    },
    // Jetbridges - 5 gates matching backend GATES positions
    // Backend gate positions map to 3D x:
    //   A1: lon -122.016 → x ≈ -128 (wide-body)
    //   A2: lon -122.008 → x ≈ -64
    //   A3: lon -122.000 → x ≈ 0 (center)
    //   B1: lon -121.992 → x ≈ +64
    //   B2: lon -121.984 → x ≈ +128 (wide-body)
    // Gate spacing: 0.008 deg = ~64 3D units (ensures MIN_GATE_SEPARATION)
    {
      id: 'jetbridge-A1',
      type: 'jetbridge',
      position: { x: -128, y: 0, z: 40 },  // Gate A1 (wide-body)
      rotation: Math.PI / 2,
    },
    {
      id: 'jetbridge-A2',
      type: 'jetbridge',
      position: { x: -64, y: 0, z: 40 },   // Gate A2
      rotation: Math.PI / 2,
    },
    {
      id: 'jetbridge-A3',
      type: 'jetbridge',
      position: { x: 0, y: 0, z: 40 },     // Gate A3 (center)
      rotation: Math.PI / 2,
    },
    {
      id: 'jetbridge-B1',
      type: 'jetbridge',
      position: { x: 64, y: 0, z: 40 },    // Gate B1
      rotation: Math.PI / 2,
    },
    {
      id: 'jetbridge-B2',
      type: 'jetbridge',
      position: { x: 128, y: 0, z: 40 },   // Gate B2 (wide-body)
      rotation: Math.PI / 2,
    },
    // Fire station - near runway
    {
      id: 'fire-station-1',
      type: 'fire-station',
      position: { x: 300, y: 0, z: -200 },
      rotation: 0,
    },
    // Fuel station
    {
      id: 'fuel-station-1',
      type: 'fuel-station',
      position: { x: -250, y: 0, z: 200 },
      rotation: 0,
    },
  ],

  // Ground plane configuration
  ground: {
    size: 2000,
    color: 0x228b22, // Grass green
  },

  // Scene lighting configuration
  lighting: {
    ambient: {
      intensity: 0.8,
    },
    directional: {
      position: { x: 100, y: 100, z: 50 },
      intensity: 0.9,
    },
  },
};

// Color constants for runway markings
export const RUNWAY_MARKING_COLOR = 0xffffff; // White

// Color constants for additional elements
export const COLORS = {
  runwayMarking: 0xffffff, // White
  taxiwayMarking: 0xffcc00, // Yellow
  aircraftDefault: 0xff6600, // Orange
  aircraftSelected: 0x00ff00, // Green
  aircraftArriving: 0x4a90d9, // Blue
  aircraftDeparting: 0xd94a4a, // Red
  separationWarning: 0xffaa00, // Orange - close to minimum separation
  separationViolation: 0xff0000, // Red - below minimum separation
} as const;

// ============================================================================
// SEPARATION CONSTRAINTS (FAA/ICAO Standards) - 3D Scale
// Convert from degrees to 3D scene units
// Scale: 1 deg ≈ 10000 scene units (approx)
// ============================================================================

// 3D scene scale factor for separations
export const SCENE_SCALE = 10000;

// Minimum approach separation in 3D units (3 NM = ~3000 scene units)
export const MIN_APPROACH_SEPARATION_3D = 3.0 * (1 / 60) * SCENE_SCALE;

// Minimum taxi separation in 3D units (~100m = ~10 scene units)
export const MIN_TAXI_SEPARATION_3D = 0.001 * SCENE_SCALE;

// Minimum gate separation in 3D units (~200m = ~20 scene units)
export const MIN_GATE_SEPARATION_3D = 0.002 * SCENE_SCALE;

// Capacity limits (same as backend)
export const CAPACITY_LIMITS = {
  maxApproach: 4,    // Max aircraft on approach
  maxParked: 5,      // Max parked at gates
  maxTaxi: 2,        // Max taxiing at once
} as const;

// Gate positions in 3D coordinates (matching backend)
export const GATE_POSITIONS_3D = {
  A1: { x: -128, y: 0, z: 90 },  // Wide-body capable
  A2: { x: -64, y: 0, z: 90 },
  A3: { x: 0, y: 0, z: 90 },     // Center gate
  B1: { x: 64, y: 0, z: 90 },
  B2: { x: 128, y: 0, z: 90 },   // Wide-body capable
} as const;
