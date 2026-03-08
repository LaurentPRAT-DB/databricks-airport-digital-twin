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

export interface AircraftModelConfig {
  url: string;
  scale: number;
  rotationOffset: { x: number; y: number; z: number };
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
 * Scale reference (scene units = meters):
 * - Terminal: 200 units wide (~200m)
 * - Runway width: 45 units (~45m)
 * - B737 wingspan: ~35.8m → target ~36 units
 * - A320 wingspan: ~35.8m → target ~36 units
 * - A380 wingspan: ~79.8m → target ~80 units
 *
 * Native model sizes (measured from GLB accessor bounds):
 * - generic-jet.glb: 2.0 units → scale 17.5 for 35m wingspan
 * - boeing-737.glb: 12.1 units (X) → scale 2.96 for 35.8m wingspan
 * - airbus-a320.glb: 28.0 units (X) → scale 1.28 for 35.8m wingspan
 * - air_france_airbus_a318-100.glb: 34.0 units → scale 1.0 for 34m
 * - airbus_a380.glb: 79.7 units → scale 1.0 for 80m wingspan
 */
export const AIRCRAFT_MODELS: Record<string, AircraftModelConfig> = {
  // Boeing narrow body (wingspan ~35.8m)
  // boeing-737.glb: measured native wingspan 12.1 units, target 35.8m → scale 2.96
  'B737': { url: '/models/aircraft/boeing-737.glb', scale: 2.96, rotationOffset: { x: 0, y: 0, z: 0 } },
  'B738': { url: '/models/aircraft/boeing-737.glb', scale: 2.96, rotationOffset: { x: 0, y: 0, z: 0 } },
  'B739': { url: '/models/aircraft/boeing-737.glb', scale: 3.1, rotationOffset: { x: 0, y: 0, z: 0 } },

  // Airbus narrow body (wingspan ~34-36m)
  // airbus-a320.glb: measured native wingspan 28 units, target 35.8m → scale 1.28
  'A318': { url: '/models/aircraft/airbus-a320.glb', scale: 1.22, rotationOffset: { x: 0, y: 0, z: 0 } },
  'A319': { url: '/models/aircraft/airbus-a320.glb', scale: 1.25, rotationOffset: { x: 0, y: 0, z: 0 } },
  'A320': { url: '/models/aircraft/airbus-a320.glb', scale: 1.28, rotationOffset: { x: 0, y: 0, z: 0 } },
  'A321': { url: '/models/aircraft/airbus-a320.glb', scale: 1.28, rotationOffset: { x: 0, y: 0, z: 0 } },

  // Airbus wide body (wingspan ~60-80m)
  // airbus_a380.glb: measured 79.7 units, target 79.8m → scale 1.0
  'A310': { url: '/models/aircraft/airbus_a320.glb', scale: 1.55, rotationOffset: { x: 0, y: 0, z: 0 } },
  'A330': { url: '/models/aircraft/cathay_pacific_airbus_a330-300.glb', scale: 1.0, rotationOffset: { x: 0, y: 0, z: 0 } },
  'A340': { url: '/models/aircraft/airbus_a345.glb', scale: 1.0, rotationOffset: { x: 0, y: 0, z: 0 } },
  'A345': { url: '/models/aircraft/airbus_a345.glb', scale: 1.0, rotationOffset: { x: 0, y: 0, z: 0 } },
  'A380': { url: '/models/aircraft/airbus_a380.glb', scale: 1.0, rotationOffset: { x: 0, y: 0, z: 0 } },

  // Boeing wide body (wingspan ~60-65m)
  'B777': { url: '/models/aircraft/cathay_pacific_airbus_a330-300.glb', scale: 1.03, rotationOffset: { x: 0, y: 0, z: 0 } },
  'B787': { url: '/models/aircraft/cathay_pacific_airbus_a330-300.glb', scale: 1.0, rotationOffset: { x: 0, y: 0, z: 0 } },

  // Generic fallback - generic-jet.glb native 2.0 units, target 35m wingspan
  'DEFAULT': { url: '/models/aircraft/generic-jet.glb', scale: 17.5, rotationOffset: { x: 0, y: Math.PI, z: 0 } },
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
  // emirates_airbus_a345.glb: measured 63.5 units, target 63.5m → scale 1.0
  'UAE_A345': { url: '/models/aircraft/emirates_airbus_a345.glb', scale: 1.0, rotationOffset: { x: 0, y: 0, z: 0 } },
  'UAE_A340': { url: '/models/aircraft/emirates_airbus_a345.glb', scale: 1.0, rotationOffset: { x: 0, y: 0, z: 0 } },
  'UAE_A380': { url: '/models/aircraft/airbus_a380.glb', scale: 1.0, rotationOffset: { x: 0, y: 0, z: 0 } },

  // Air France (narrow body ~34m wingspan) - native 34 units, target 34.1m → scale 1.0
  'AFR_A318': { url: '/models/aircraft/air_france_airbus_a318-100.glb', scale: 1.0, rotationOffset: { x: 0, y: 0, z: 0 } },
  'AFR_A319': { url: '/models/aircraft/air_france_airbus_a318-100.glb', scale: 1.03, rotationOffset: { x: 0, y: 0, z: 0 } },
  'AFR_A320': { url: '/models/aircraft/air_france_airbus_a318-100.glb', scale: 1.05, rotationOffset: { x: 0, y: 0, z: 0 } },

  // Cathay Pacific (wide body ~60.3m wingspan for A330-300)
  // cathay_pacific_airbus_a330-300.glb: measured 60.9 units, target 60.3m → scale ~1.0
  'CPA_A330': { url: '/models/aircraft/cathay_pacific_airbus_a330-300.glb', scale: 1.0, rotationOffset: { x: 0, y: 0, z: 0 } },
  'CPA_A333': { url: '/models/aircraft/cathay_pacific_airbus_a330-300.glb', scale: 1.0, rotationOffset: { x: 0, y: 0, z: 0 } },
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
