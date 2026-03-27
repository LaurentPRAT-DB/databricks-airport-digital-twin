/**
 * Aircraft Model Configuration
 *
 * Maps aircraft types and airlines to 3D models and textures.
 *
 * To add new models:
 * 1. Download GLB files from Sketchfab (CC licensed)
 * 2. Place in public/models/aircraft/
 * 3. Add mapping below
 *
 * Recommended sources for free models:
 * - Sketchfab: https://sketchfab.com/search?q=aircraft+glb&type=models
 * - Poly Haven: https://polyhaven.com/
 * - NASA 3D: https://nasa3d.arc.nasa.gov/
 */

import { METERS_TO_SCENE_UNITS } from '../utils/map3d-calculations';

// Global aircraft visual scale adjustment (0.7 = 30% smaller for better visual proportion vs terminals)
export const AIRCRAFT_VISUAL_SCALE = 0.7;

export interface AircraftModelConfig {
  url: string;
  scale: number;
  rotationOffset: { x: number; y: number; z: number };
  /** When set, only show nodes whose name starts with this prefix (for multi-model GLBs) */
  nodePrefix?: string;
}

export interface AirlineConfig {
  name: string;
  primaryColor: number;
  secondaryColor: number;
  logoUrl?: string;
}

/**
 * Aircraft type to model mapping
 * Keys are ICAO aircraft type codes (e.g., B738, A320)
 *
 * Scale includes METERS_TO_SCENE_UNITS correction (≈0.0898) so that GLTF models
 * (sized in real meters) match the latLonTo3D landscape coordinate system
 * where 1 scene unit ≈ 11.13 meters.
 *
 * Effective model sizes (bounding box after internal node transforms):
 * - generic-jet.glb: 2.0m → base scale 17.5 × 0.0898 = 1.572
 * - boeing-737.glb: 34.9m (Z, length) — node scales [1,17,1.91] inflate raw 12.1→34.9
 *   base scale 1.03 × 0.0898 = 0.0925 (targets 35.8m wingspan)
 * - airbus_a320.glb: 37.7m (Z, length) → base scale 1.05 × 0.0898 = 0.0943
 * - air_france_airbus_a318-100.glb: 34.0m → base scale 1.0 × 0.0898
 * - cathay_pacific_airbus_a330-300.glb: 64.2m (Z) → base scale 1.0 × 0.0898
 * - airbus_a345.glb: 67.9m (Y, length) → base scale 1.0 × 0.0898
 * - airbus_a380.glb: 79.7m → base scale 1.0 × 0.0898
 */
export const AIRCRAFT_MODELS: Record<string, AircraftModelConfig> = {
  // Boeing narrow body (wingspan ~35.8m)
  // boeing-737.glb has internal node scales [1,17,1.91] — effective size ~34.9m, not raw 12.1m
  'B737': { url: '/models/aircraft/boeing-737.glb', scale: 1.03 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },
  'B738': { url: '/models/aircraft/boeing-737.glb', scale: 1.03 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },
  'B739': { url: '/models/aircraft/boeing-737.glb', scale: 1.08 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },

  // Airbus narrow body (wingspan ~34-36m)
  // airbus_a320.glb native wingspan 34.2 units (1:1 meters)
  'A318': { url: '/models/aircraft/airbus_a320.glb', scale: 0.97 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },  // A318 wingspan 34.1m
  'A319': { url: '/models/aircraft/airbus_a320.glb', scale: 1.0 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },   // A319 wingspan 35.8m
  'A320': { url: '/models/aircraft/airbus_a320.glb', scale: 1.05 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },  // A320 wingspan 35.8m
  'A321': { url: '/models/aircraft/airbus_a320.glb', scale: 1.05 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },  // A321 wingspan 35.8m

  // Airbus wide body (wingspan ~60-80m)
  'A310': { url: '/models/aircraft/airbus_a320.glb', scale: 1.55 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },
  'A330': { url: '/models/aircraft/cathay_pacific_airbus_a330-300.glb', scale: 1.0 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },
  'A340': { url: '/models/aircraft/airbus_a345.glb', scale: 1.0 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },
  'A345': { url: '/models/aircraft/airbus_a345.glb', scale: 1.0 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },
  'A350': { url: '/models/aircraft/cathay_pacific_airbus_a330-300.glb', scale: 1.06 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } }, // A350 wingspan 64.8m, A330 model native 60.9 units
  'A380': { url: '/models/aircraft/airbus_a380.glb', scale: 1.0 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },

  // Boeing wide body (wingspan ~60-65m)
  'B777': { url: '/models/aircraft/cathay_pacific_airbus_a330-300.glb', scale: 1.03 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },
  'B787': { url: '/models/aircraft/cathay_pacific_airbus_a330-300.glb', scale: 1.0 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },

  // Fighter jets (from fighter jet collection GLB — units are ~10x real meters)
  // F-14 Tomcat: real wingspan 19.5m, model Y span ~196 units → scale 19.5/196 ≈ 0.0995
  'F14': { url: '/models/aircraft/free_-_fighter_jet_collection_-_low_poly.glb', scale: 0.1 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: Math.PI / 2, z: 0 }, nodePrefix: 'F-14' },
  // F-15 Eagle: real wingspan 13.1m, model Y span ~131 → scale 13.1/131 ≈ 0.1
  'F15': { url: '/models/aircraft/free_-_fighter_jet_collection_-_low_poly.glb', scale: 0.1 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: Math.PI / 2, z: 0 }, nodePrefix: 'F-15' },
  // F-16 Falcon: real wingspan 9.4m, model Y span ~94 → scale 9.4/94 ≈ 0.1
  'F16': { url: '/models/aircraft/free_-_fighter_jet_collection_-_low_poly.glb', scale: 0.1 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: Math.PI / 2, z: 0 }, nodePrefix: 'F-16' },
  // F/A-18 Hornet: real wingspan 11.4m, model Y span ~130 → scale 11.4/130 ≈ 0.088
  'F18': { url: '/models/aircraft/free_-_fighter_jet_collection_-_low_poly.glb', scale: 0.088 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: Math.PI / 2, z: 0 }, nodePrefix: 'F-18' },
  // F-22 Raptor: real wingspan 13.6m, model Y span ~136 → scale 13.6/136 ≈ 0.1
  'F22': { url: '/models/aircraft/free_-_fighter_jet_collection_-_low_poly.glb', scale: 0.1 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: Math.PI / 2, z: 0 }, nodePrefix: 'F-22' },
  // F-35 Lightning: real wingspan 10.7m, model Y span ~132 → scale 10.7/132 ≈ 0.081
  'F35': { url: '/models/aircraft/free_-_fighter_jet_collection_-_low_poly.glb', scale: 0.081 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: Math.PI / 2, z: 0 }, nodePrefix: 'F-35' },

  // Generic fallback - generic-jet.glb native 2.0 units, target 35m wingspan
  'DEFAULT': { url: '/models/aircraft/generic-jet.glb', scale: 17.5 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: Math.PI, z: 0 } },
};

/**
 * Airline-specific GLB models with pre-baked liveries
 * Key format: "AIRLINE_AIRCRAFT" (e.g., "UAE_A345" for Emirates A345)
 *
 * Measured native sizes (from GLB accessor bounds):
 * - air_france_airbus_a318-100.glb: 34.0 units (wingspan) - 1:1 scale in meters
 * - emirates_airbus_a345.glb: 63.5 units (wingspan) - 1:1 scale in meters
 * - cathay_pacific_airbus_a330-300.glb: 60.9 units (wingspan) - 1:1 scale in meters
 * - airbus_a380.glb: 79.7 units (wingspan) - 1:1 scale in meters
 */
export const AIRLINE_SPECIFIC_MODELS: Record<string, AircraftModelConfig> = {
  // Emirates (wide body ~63.5m wingspan for A340-500/600)
  'UAE_A345': { url: '/models/aircraft/emirates_airbus_a345.glb', scale: 1.0 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },
  'UAE_A340': { url: '/models/aircraft/emirates_airbus_a345.glb', scale: 1.0 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },
  'UAE_A380': { url: '/models/aircraft/airbus_a380.glb', scale: 1.0 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },

  // Air France (narrow body ~34m wingspan)
  'AFR_A318': { url: '/models/aircraft/air_france_airbus_a318-100.glb', scale: 1.0 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },
  'AFR_A319': { url: '/models/aircraft/air_france_airbus_a318-100.glb', scale: 1.03 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },
  'AFR_A320': { url: '/models/aircraft/air_france_airbus_a318-100.glb', scale: 1.05 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },

  // Cathay Pacific (wide body ~60.3m wingspan for A330-300)
  'CPA_A330': { url: '/models/aircraft/cathay_pacific_airbus_a330-300.glb', scale: 1.0 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },
  'CPA_A333': { url: '/models/aircraft/cathay_pacific_airbus_a330-300.glb', scale: 1.0 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE, rotationOffset: { x: 0, y: 0, z: 0 } },
};

/**
 * Airline configuration by ICAO code
 * Extract from callsign (first 3 chars)
 */
export const AIRLINES: Record<string, AirlineConfig> = {
  // US Major Airlines
  'UAL': { name: 'United Airlines', primaryColor: 0x002244, secondaryColor: 0x0066CC },
  'DAL': { name: 'Delta Air Lines', primaryColor: 0x003366, secondaryColor: 0xE21A23 },
  'AAL': { name: 'American Airlines', primaryColor: 0x0078D2, secondaryColor: 0xB6B8DC },
  'SWA': { name: 'Southwest Airlines', primaryColor: 0x304CB2, secondaryColor: 0xFFBF27 },
  'JBU': { name: 'JetBlue Airways', primaryColor: 0x003876, secondaryColor: 0x00B2E2 },
  'ASA': { name: 'Alaska Airlines', primaryColor: 0x01426A, secondaryColor: 0x64CCC9 },

  // International
  'BAW': { name: 'British Airways', primaryColor: 0x075AAA, secondaryColor: 0xEB2226 },
  'AFR': { name: 'Air France', primaryColor: 0x002157, secondaryColor: 0xED1C24 },
  'DLH': { name: 'Lufthansa', primaryColor: 0x05164D, secondaryColor: 0xFFCC00 },
  'KLM': { name: 'KLM', primaryColor: 0x00A1E4, secondaryColor: 0xFFFFFF },
  'ANA': { name: 'All Nippon Airways', primaryColor: 0x13448F, secondaryColor: 0x00B5E2 },
  'JAL': { name: 'Japan Airlines', primaryColor: 0xE60012, secondaryColor: 0xFFFFFF },
  'SIA': { name: 'Singapore Airlines', primaryColor: 0xF7B500, secondaryColor: 0x003D7C },
  'QFA': { name: 'Qantas', primaryColor: 0xE0001A, secondaryColor: 0xFFFFFF },
  'UAE': { name: 'Emirates', primaryColor: 0xD71921, secondaryColor: 0xC69C6D },
  'CPA': { name: 'Cathay Pacific', primaryColor: 0x006564, secondaryColor: 0xA6A8AA },

  // Ukrainian (Easter egg)
  'AUI': { name: 'Ukraine International Airlines', primaryColor: 0x005BBB, secondaryColor: 0xFFD500 },
  'UAF': { name: 'Ukrainian Air Force', primaryColor: 0x005BBB, secondaryColor: 0xFFD500 },

  // Default
  'DEFAULT': { name: 'Unknown Airline', primaryColor: 0x888888, secondaryColor: 0xCCCCCC },
};

/**
 * Extract airline code from callsign
 */
export function getAirlineFromCallsign(callsign: string | null): AirlineConfig {
  if (!callsign || callsign.length < 3) {
    return AIRLINES['DEFAULT'];
  }
  const airlineCode = callsign.substring(0, 3).toUpperCase();
  return AIRLINES[airlineCode] || AIRLINES['DEFAULT'];
}

/**
 * Get model config for aircraft type, optionally checking airline-specific models first
 * @param aircraftType ICAO aircraft type code (e.g., A320, B738)
 * @param airlineCode ICAO airline code from callsign (e.g., UAE, AFR)
 */
export function getModelForAircraftType(aircraftType?: string, airlineCode?: string): AircraftModelConfig {
  // First, check for airline-specific model with pre-baked livery
  if (airlineCode && aircraftType) {
    const specificKey = `${airlineCode.toUpperCase()}_${aircraftType.toUpperCase()}`;
    if (AIRLINE_SPECIFIC_MODELS[specificKey]) {
      return AIRLINE_SPECIFIC_MODELS[specificKey];
    }
  }

  // Fall back to generic aircraft type model
  if (aircraftType) {
    const model = AIRCRAFT_MODELS[aircraftType.toUpperCase()];
    if (model) {
      return model;
    }
  }

  return AIRCRAFT_MODELS['DEFAULT'];
}

/**
 * Check if a model file exists (client-side check)
 */
export async function modelExists(url: string): Promise<boolean> {
  try {
    const response = await fetch(url, { method: 'HEAD' });
    return response.ok;
  } catch {
    return false;
  }
}
