// Re-export DEFAULT_ZOOM from centralized defaults for backwards compatibility
export { DEFAULT_ZOOM } from './defaults';

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
