/**
 * Pure calculation functions for 3D map visualization
 *
 * These functions contain no WebGL/Three.js dependencies and can be unit tested.
 * They are extracted from 3D components to improve testability.
 */

// ============================================================================
// Coordinate Transformations
// ============================================================================

/** Default airport center coordinates (SFO) */
export const DEFAULT_CENTER_LAT = 37.6213;
export const DEFAULT_CENTER_LON = -122.379;
export const DEFAULT_COORDINATE_SCALE = 10000;

/**
 * Altitude scale factor for 3D visualization
 * Converts feet to scene units with exaggeration for visual clarity
 *
 * Real scale would be ~0.003 (1ft = 0.3048m, 1m = 0.01 scene units)
 * Using 0.15 for 50x exaggeration so altitude differences are visible
 *
 * At this scale:
 * - Ground (0 ft) → Y = 5
 * - 1,000 ft → Y = 50
 * - 5,000 ft → Y = 234
 * - 10,000 ft → Y = 462
 */
export const ALTITUDE_SCALE = 0.15;

export interface Position3D {
  x: number;
  y: number;
  z: number;
}

/**
 * Convert lat/lon to 3D scene coordinates
 *
 * Maps real-world lat/lon coordinates to the 3D airport scene.
 * - X axis: East-West (positive = East)
 * - Z axis: North-South (negative = North)
 * - Y axis: Altitude
 */
export function latLonTo3D(
  lat: number,
  lon: number,
  altitude: number | null = 0,
  centerLat: number = DEFAULT_CENTER_LAT,
  centerLon: number = DEFAULT_CENTER_LON,
  scale: number = DEFAULT_COORDINATE_SCALE
): Position3D {
  // Longitude → X axis (scaled by cos(lat) for Mercator projection)
  const x = (lon - centerLon) * scale * Math.cos(centerLat * Math.PI / 180);
  // Latitude → Z axis (negative because Z points south in scene)
  const z = -(lat - centerLat) * scale;
  // Altitude from feet to scene units (exaggerated for visibility)
  const altitudeMeters = (altitude || 0) * 0.3048;
  const y = altitudeMeters * ALTITUDE_SCALE + 5; // Scale + ground offset

  return { x, y, z };
}

/**
 * Convert 3D scene coordinates back to lat/lon
 */
export function position3DToLatLon(
  pos: Position3D,
  centerLat: number = DEFAULT_CENTER_LAT,
  centerLon: number = DEFAULT_CENTER_LON,
  scale: number = DEFAULT_COORDINATE_SCALE
): { lat: number; lon: number; altitude: number } {
  const lat = centerLat - pos.z / scale;
  const lon = centerLon + pos.x / (scale * Math.cos(centerLat * Math.PI / 180));
  const altitudeMeters = (pos.y - 5) / ALTITUDE_SCALE;
  const altitude = altitudeMeters / 0.3048;

  return { lat, lon, altitude };
}

// ============================================================================
// Aircraft Animation Calculations
// ============================================================================

/**
 * Convert compass heading to scene rotation (radians)
 * Heading is degrees clockwise from north; scene Z is forward
 */
export function headingToRotation(heading: number | null): number {
  return ((heading || 0) - 90) * Math.PI / 180;
}

/**
 * Calculate frame-rate independent lerp factor
 * Ensures consistent animation speed regardless of frame rate
 */
export function calculateLerpFactor(delta: number, baseSpeed: number = 0.1): number {
  return Math.min(baseSpeed * delta * 60, 1);
}

/**
 * Normalize rotation difference for smooth interpolation
 * Handles angle wrapping at ±π to take shortest path
 */
export function normalizeRotationDiff(current: number, target: number): number {
  const diff = target - current;
  if (Math.abs(diff) > Math.PI) {
    return diff > 0 ? diff - 2 * Math.PI : diff + 2 * Math.PI;
  }
  return diff;
}

/**
 * Calculate new rotation with smooth interpolation
 */
export function interpolateRotation(
  current: number,
  target: number,
  lerpFactor: number
): number {
  const adjustedDiff = normalizeRotationDiff(current, target);
  return current + adjustedDiff * lerpFactor;
}

// ============================================================================
// Trajectory Visualization
// ============================================================================

export interface TrajectoryPoint {
  latitude: number | null;
  longitude: number | null;
  altitude: number | null;
}

export interface RGB {
  r: number;
  g: number;
  b: number;
}

/**
 * Filter trajectory points to only those with valid coordinates
 */
export function filterValidTrajectoryPoints<T extends TrajectoryPoint>(
  points: T[]
): T[] {
  return points.filter(p => p.latitude !== null && p.longitude !== null);
}

/**
 * Calculate color gradient for trajectory visualization
 * Older points are lighter blue, newer points are brighter
 */
export function calculateTrajectoryColor(index: number, totalPoints: number): RGB {
  const t = totalPoints > 1 ? index / (totalPoints - 1) : 0;
  return {
    r: 0.2 + t * 0.1,
    g: 0.4 + t * 0.2,
    b: 0.8 + t * 0.2,
  };
}

/**
 * Generate indices for sampling points at regular intervals
 * Used to display markers without overwhelming the scene
 */
export function samplePointIndices(
  totalPoints: number,
  targetSamples: number
): number[] {
  if (totalPoints <= targetSamples) {
    return Array.from({ length: totalPoints }, (_, i) => i);
  }

  const interval = Math.max(1, Math.floor(totalPoints / targetSamples));
  const indices: number[] = [];

  for (let i = 0; i < totalPoints; i++) {
    if (i % interval === 0) {
      indices.push(i);
    }
  }

  return indices;
}

// ============================================================================
// Runway & Taxiway Geometry
// ============================================================================

export interface Point2D {
  x: number;
  z: number;
  y?: number;
}

export interface RunwayGeometry {
  length: number;
  centerX: number;
  centerZ: number;
  angle: number;
}

/**
 * Calculate runway geometry from start/end points
 */
export function calculateRunwayGeometry(
  start: Point2D,
  end: Point2D
): RunwayGeometry {
  const length = Math.sqrt(
    Math.pow(end.x - start.x, 2) + Math.pow(end.z - start.z, 2)
  );
  const centerX = (start.x + end.x) / 2;
  const centerZ = (start.z + end.z) / 2;
  const angle = Math.atan2(end.z - start.z, end.x - start.x);

  return { length, centerX, centerZ, angle };
}

export interface MarkingPosition {
  x: number;
  width: number;
}

/**
 * Generate runway center line marking positions
 */
export function generateRunwayMarkings(
  runwayLength: number,
  markingLength: number = 30,
  gapLength: number = 20,
  endBuffer: number = 40
): MarkingPosition[] {
  const markings: MarkingPosition[] = [];
  const totalLength = runwayLength - endBuffer;
  let pos = -totalLength / 2;

  while (pos < totalLength / 2) {
    markings.push({
      x: pos + markingLength / 2,
      width: markingLength,
    });
    pos += markingLength + gapLength;
  }

  return markings;
}

/**
 * Generate threshold stripe positions
 */
export function generateThresholdStripes(
  runwayWidth: number,
  stripeWidth: number = 3,
  gap: number = 3,
  margin: number = 10
): number[] {
  const numStripes = Math.floor((runwayWidth - margin) / (stripeWidth + gap));
  const startZ = -((numStripes - 1) * (stripeWidth + gap)) / 2;

  return Array.from(
    { length: numStripes },
    (_, i) => startZ + i * (stripeWidth + gap)
  );
}

/**
 * Calculate taxiway segment geometry
 */
export function calculateTaxiwaySegment(
  start: Point2D,
  end: Point2D
): RunwayGeometry {
  // Same calculation as runway
  return calculateRunwayGeometry(start, end);
}

// ============================================================================
// Airline & Aircraft Utilities
// ============================================================================

/**
 * Extract airline code (first 3 chars) from callsign
 */
export function extractAirlineCode(callsign: string | null): string | null {
  if (!callsign || callsign.length < 3) {
    return null;
  }
  return callsign.substring(0, 3).toUpperCase();
}

/**
 * Determine mesh color type from mesh name
 * Used for applying airline livery colors
 */
export type MeshColorType =
  | 'tail'      // Secondary color (logos)
  | 'fuselage'  // Primary color
  | 'engine'    // Metallic gray
  | 'window'    // Dark
  | 'default';  // Primary color

export function getMeshColorType(meshName: string): MeshColorType {
  const name = meshName.toLowerCase();

  if (name.includes('tail') || name.includes('fin') || name.includes('logo')) {
    return 'tail';
  }
  if (name.includes('fuselage') || name.includes('body')) {
    return 'fuselage';
  }
  if (name.includes('engine') || name.includes('wheel') || name.includes('gear')) {
    return 'engine';
  }
  if (name.includes('window') || name.includes('cockpit')) {
    return 'window';
  }
  return 'default';
}

// ============================================================================
// Distance & Collision Utilities
// ============================================================================

/**
 * Calculate squared distance between two 3D points
 * Squared distance avoids sqrt for performance in comparisons
 */
export function distanceSquared(a: Position3D, b: Position3D): number {
  return (
    Math.pow(a.x - b.x, 2) +
    Math.pow(a.y - b.y, 2) +
    Math.pow(a.z - b.z, 2)
  );
}

/**
 * Check if position has changed significantly
 * Used to optimize render updates
 */
export function hasPositionChanged(
  a: Position3D,
  b: Position3D,
  threshold: number = 0.0001
): boolean {
  return distanceSquared(a, b) > threshold;
}

/**
 * Check if rotation has changed significantly
 */
export function hasRotationChanged(
  a: number,
  b: number,
  threshold: number = 0.0001
): boolean {
  return Math.abs(a - b) > threshold;
}
