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

  // All geometry (runways, taxiways, buildings) comes from OSM at runtime
  runways: [],
  taxiways: [],
  buildings: [],

  // Ground plane configuration
  ground: {
    size: 2000,
    color: 0x228b22, // Grass green
  },

  // Scene lighting configuration
  lighting: {
    ambient: {
      intensity: 1.2,
    },
    directional: {
      position: { x: 100, y: 100, z: 50 },
      intensity: 1.5,
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

