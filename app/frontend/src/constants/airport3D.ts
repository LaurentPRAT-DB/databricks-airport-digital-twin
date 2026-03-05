/**
 * 3D Airport Configuration
 *
 * Defines coordinates, dimensions, and colors for 3D visualization
 * of the airport digital twin.
 */

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
} as const;
