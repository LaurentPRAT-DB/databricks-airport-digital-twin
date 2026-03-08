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

export interface TerminalConfig {
  position: Position3D;
  dimensions: Dimensions3D;
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
  terminal: TerminalConfig;
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

  // Terminal building configuration
  terminal: {
    position: { x: 0, y: 10, z: 0 },
    dimensions: { width: 200, height: 20, depth: 80 },
    color: 0x4a90d9, // Blue-gray
  },

  // Runway configurations (parallel runways)
  runways: [
    {
      id: '28L',
      start: { x: -500, y: 0.1, z: -100 },
      end: { x: 500, y: 0.1, z: -100 },
      width: 45,
      color: 0x333333, // Dark gray
    },
    {
      id: '28R',
      start: { x: -500, y: 0.1, z: 100 },
      end: { x: 500, y: 0.1, z: 100 },
      width: 45,
      color: 0x333333, // Dark gray
    },
  ],

  // Taxiway configurations
  taxiways: [
    {
      id: 'A',
      points: [
        { x: 0, y: 0.05, z: -100 },
        { x: 0, y: 0.05, z: -50 },
        { x: 0, y: 0.05, z: 0 },
      ],
      width: 20,
      color: 0x555555, // Medium gray
    },
    {
      id: 'B',
      points: [
        { x: 0, y: 0.05, z: 100 },
        { x: 0, y: 0.05, z: 50 },
        { x: 0, y: 0.05, z: 0 },
      ],
      width: 20,
      color: 0x555555, // Medium gray
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
      intensity: 0.6,
    },
    directional: {
      position: { x: 100, y: 100, z: 50 },
      intensity: 0.8,
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
