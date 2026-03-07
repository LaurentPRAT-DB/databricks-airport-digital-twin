/**
 * Airport Building Model Configuration
 *
 * Maps building types to 3D models for the airport digital twin.
 *
 * To add new models:
 * 1. Download GLB files from Sketchfab (CC licensed)
 * 2. Place in public/models/buildings/
 * 3. Add mapping below
 *
 * Recommended sources for free models:
 * - Sketchfab: https://sketchfab.com/search?q=airport+terminal&type=models&licenses=322a749bcfa841b29dff1571c1f989f0
 * - TurboSquid (free): https://www.turbosquid.com/Search/3D-Models/free/airport
 * - CGTrader (free): https://www.cgtrader.com/free-3d-models/airport
 * - Poly.pizza: https://poly.pizza/search/airport
 */

export type BuildingType =
  | 'terminal'
  | 'control-tower'
  | 'hangar'
  | 'cargo'
  | 'jetbridge'
  | 'fuel-station'
  | 'fire-station';

export interface BuildingModelConfig {
  url: string;
  scale: number;
  rotationOffset: { x: number; y: number; z: number };
  /** Whether to use procedural fallback if model not found */
  hasFallback: boolean;
}

export interface BuildingPlacement {
  id: string;
  type: BuildingType;
  position: { x: number; y: number; z: number };
  rotation: number; // Y-axis rotation in radians
  /** Optional custom scale override */
  scale?: number;
  /** Optional custom color override for procedural fallback */
  color?: number;
}

/**
 * Building type to model mapping
 */
export const BUILDING_MODELS: Record<BuildingType, BuildingModelConfig> = {
  'terminal': {
    url: '/models/buildings/terminal.glb',
    scale: 1,
    rotationOffset: { x: 0, y: 0, z: 0 },
    hasFallback: true,
  },
  'control-tower': {
    url: '/models/buildings/control-tower.glb',
    scale: 1,
    rotationOffset: { x: 0, y: 0, z: 0 },
    hasFallback: true,
  },
  'hangar': {
    url: '/models/buildings/hangar.glb',
    scale: 1,
    rotationOffset: { x: 0, y: 0, z: 0 },
    hasFallback: true,
  },
  'cargo': {
    url: '/models/buildings/cargo.glb',
    scale: 1,
    rotationOffset: { x: 0, y: 0, z: 0 },
    hasFallback: true,
  },
  'jetbridge': {
    url: '/models/buildings/jetbridge.glb',
    scale: 1,
    rotationOffset: { x: 0, y: 0, z: 0 },
    hasFallback: true,
  },
  'fuel-station': {
    url: '/models/buildings/fuel-station.glb',
    scale: 1,
    rotationOffset: { x: 0, y: 0, z: 0 },
    hasFallback: true,
  },
  'fire-station': {
    url: '/models/buildings/fire-station.glb',
    scale: 1,
    rotationOffset: { x: 0, y: 0, z: 0 },
    hasFallback: true,
  },
};

/**
 * Default building colors for procedural fallbacks
 */
export const BUILDING_COLORS: Record<BuildingType, number> = {
  'terminal': 0x4a90d9,      // Blue-gray (glass/modern)
  'control-tower': 0xe8e8e8, // Light gray (concrete)
  'hangar': 0x708090,        // Slate gray (metal)
  'cargo': 0x8b7355,         // Tan (warehouse)
  'jetbridge': 0x606060,     // Dark gray
  'fuel-station': 0xff6600,  // Orange (hazard)
  'fire-station': 0xcc0000,  // Red
};

/**
 * Procedural building dimensions (for fallback rendering)
 */
export const BUILDING_DIMENSIONS: Record<BuildingType, { width: number; height: number; depth: number }> = {
  'terminal': { width: 200, height: 20, depth: 80 },
  'control-tower': { width: 15, height: 50, depth: 15 },
  'hangar': { width: 80, height: 25, depth: 100 },
  'cargo': { width: 60, height: 15, depth: 80 },
  'jetbridge': { width: 5, height: 4, depth: 30 },
  'fuel-station': { width: 20, height: 8, depth: 20 },
  'fire-station': { width: 40, height: 12, depth: 30 },
};

/**
 * Get model config for building type
 */
export function getModelForBuildingType(buildingType: BuildingType): BuildingModelConfig {
  return BUILDING_MODELS[buildingType];
}

/**
 * Check if a model file exists (client-side check)
 */
export async function buildingModelExists(url: string): Promise<boolean> {
  try {
    const response = await fetch(url, { method: 'HEAD' });
    return response.ok;
  } catch {
    return false;
  }
}
