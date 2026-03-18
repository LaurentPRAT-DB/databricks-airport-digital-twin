import { describe, it, expect } from 'vitest';
import {
  // Coordinate transformations
  latLonTo3D,
  position3DToLatLon,
  DEFAULT_CENTER_LAT,
  DEFAULT_CENTER_LON,

  // Animation calculations
  headingToRotation,
  calculateLerpFactor,
  normalizeRotationDiff,
  interpolateRotation,

  // Trajectory
  filterValidTrajectoryPoints,
  calculateTrajectoryColor,
  samplePointIndices,

  // Runway geometry
  calculateRunwayGeometry,
  generateRunwayMarkings,
  generateThresholdStripes,
  calculateTaxiwaySegment,

  // Airline utilities
  extractAirlineCode,
  getMeshColorType,

  // Distance utilities
  distanceSquared,
  hasPositionChanged,
  hasRotationChanged,
} from './map3d-calculations';

describe('map3d-calculations', () => {
  // ========================================================================
  // Coordinate Transformations
  // ========================================================================
  describe('latLonTo3D', () => {
    it('converts center point to origin', () => {
      const pos = latLonTo3D(DEFAULT_CENTER_LAT, DEFAULT_CENTER_LON, 0);
      expect(pos.x).toBeCloseTo(0, 5);
      expect(pos.z).toBeCloseTo(0, 5);
      expect(pos.y).toBe(0.5); // Ground level (just above surface)
    });

    it('handles points north of center (negative Z)', () => {
      const pos = latLonTo3D(DEFAULT_CENTER_LAT + 0.01, DEFAULT_CENTER_LON, 0);
      expect(pos.z).toBeLessThan(0); // North = negative Z
    });

    it('handles points east of center (positive X)', () => {
      const pos = latLonTo3D(DEFAULT_CENTER_LAT, DEFAULT_CENTER_LON + 0.01, 0);
      expect(pos.x).toBeGreaterThan(0); // East = positive X
    });

    it('handles points south of center (positive Z)', () => {
      const pos = latLonTo3D(DEFAULT_CENTER_LAT - 0.01, DEFAULT_CENTER_LON, 0);
      expect(pos.z).toBeGreaterThan(0); // South = positive Z
    });

    it('handles points west of center (negative X)', () => {
      const pos = latLonTo3D(DEFAULT_CENTER_LAT, DEFAULT_CENTER_LON - 0.01, 0);
      expect(pos.x).toBeLessThan(0); // West = negative X
    });

    it('converts altitude from feet to scene units', () => {
      const pos0 = latLonTo3D(DEFAULT_CENTER_LAT, DEFAULT_CENTER_LON, 0);
      const pos1000 = latLonTo3D(DEFAULT_CENTER_LAT, DEFAULT_CENTER_LON, 1000);
      expect(pos1000.y).toBeGreaterThan(pos0.y);
    });

    it('handles null altitude as 0', () => {
      const pos = latLonTo3D(DEFAULT_CENTER_LAT, DEFAULT_CENTER_LON, null);
      expect(pos.y).toBe(0.5); // Ground level
    });

    it('scales correctly with custom scale factor', () => {
      const scale1 = latLonTo3D(37.51, -122.0, 0, 37.5, -122.0, 10000);
      const scale2 = latLonTo3D(37.51, -122.0, 0, 37.5, -122.0, 20000);
      expect(Math.abs(scale2.z)).toBeCloseTo(Math.abs(scale1.z) * 2, 1);
    });
  });

  describe('position3DToLatLon', () => {
    it('converts origin back to center coordinates', () => {
      const result = position3DToLatLon({ x: 0, y: 0.5, z: 0 });
      expect(result.lat).toBeCloseTo(DEFAULT_CENTER_LAT, 5);
      expect(result.lon).toBeCloseTo(DEFAULT_CENTER_LON, 5);
      expect(result.altitude).toBe(0); // Ground level
    });

    it('is inverse of latLonTo3D', () => {
      const originalLat = 37.52;
      const originalLon = -121.98;
      const altitude = 5000;

      const pos3D = latLonTo3D(originalLat, originalLon, altitude);
      const result = position3DToLatLon(pos3D);

      expect(result.lat).toBeCloseTo(originalLat, 4);
      expect(result.lon).toBeCloseTo(originalLon, 4);
      expect(result.altitude).toBeCloseTo(altitude, 0);
    });
  });

  // ========================================================================
  // Animation Calculations
  // ========================================================================
  describe('headingToRotation', () => {
    it('converts north (0°) to +90° rotation', () => {
      const rot = headingToRotation(0);
      expect(rot).toBeCloseTo(Math.PI / 2, 5);
    });

    it('converts east (90°) to 0° rotation', () => {
      const rot = headingToRotation(90);
      expect(rot).toBeCloseTo(0, 5);
    });

    it('converts south (180°) to -90° rotation', () => {
      const rot = headingToRotation(180);
      expect(rot).toBeCloseTo(-Math.PI / 2, 5);
    });

    it('converts west (270°) to -180° rotation', () => {
      const rot = headingToRotation(270);
      expect(rot).toBeCloseTo(-Math.PI, 5);
    });

    it('handles null heading as 0', () => {
      const rot = headingToRotation(null);
      expect(rot).toBeCloseTo(Math.PI / 2, 5);
    });
  });

  describe('calculateLerpFactor', () => {
    it('returns base speed at 60fps (delta ~0.0167)', () => {
      const factor = calculateLerpFactor(1 / 60, 0.1);
      expect(factor).toBeCloseTo(0.1, 2);
    });

    it('adjusts for slower frame rate', () => {
      const factor30fps = calculateLerpFactor(1 / 30, 0.1);
      const factor60fps = calculateLerpFactor(1 / 60, 0.1);
      expect(factor30fps).toBeGreaterThan(factor60fps);
    });

    it('caps at 1.0 for very large delta', () => {
      const factor = calculateLerpFactor(1, 0.1); // 1 second frame
      expect(factor).toBe(1);
    });

    it('uses custom base speed', () => {
      const factor1 = calculateLerpFactor(1 / 60, 0.1);
      const factor2 = calculateLerpFactor(1 / 60, 0.2);
      expect(factor2).toBeCloseTo(factor1 * 2, 2);
    });
  });

  describe('normalizeRotationDiff', () => {
    it('returns direct diff for small angles', () => {
      const diff = normalizeRotationDiff(0, 0.5);
      expect(diff).toBeCloseTo(0.5, 5);
    });

    it('wraps positive diff greater than π', () => {
      const diff = normalizeRotationDiff(0, Math.PI + 0.5);
      expect(diff).toBeLessThan(0); // Should take shorter negative path
      expect(diff).toBeCloseTo(-Math.PI + 0.5, 5);
    });

    it('wraps negative diff less than -π', () => {
      const diff = normalizeRotationDiff(0, -Math.PI - 0.5);
      expect(diff).toBeGreaterThan(0); // Should take shorter positive path
      expect(diff).toBeCloseTo(Math.PI - 0.5, 5);
    });

    it('handles exactly π', () => {
      const diff = normalizeRotationDiff(0, Math.PI);
      expect(Math.abs(diff)).toBeCloseTo(Math.PI, 5);
    });
  });

  describe('interpolateRotation', () => {
    it('moves toward target', () => {
      const result = interpolateRotation(0, 1, 0.5);
      expect(result).toBeCloseTo(0.5, 5);
    });

    it('returns target when lerp is 1', () => {
      const result = interpolateRotation(0, 2, 1);
      expect(result).toBeCloseTo(2, 5);
    });

    it('takes shortest path across π boundary', () => {
      const result = interpolateRotation(Math.PI - 0.1, -Math.PI + 0.1, 0.5);
      // Should cross through ±π, not go the long way
      expect(Math.abs(result)).toBeGreaterThan(Math.PI - 0.2);
    });
  });

  // ========================================================================
  // Trajectory Visualization
  // ========================================================================
  describe('filterValidTrajectoryPoints', () => {
    it('filters out points with null latitude', () => {
      const points = [
        { latitude: 37.5, longitude: -122.0, altitude: 1000 },
        { latitude: null, longitude: -122.0, altitude: 1000 },
        { latitude: 37.6, longitude: -122.1, altitude: 2000 },
      ];
      const result = filterValidTrajectoryPoints(points);
      expect(result).toHaveLength(2);
    });

    it('filters out points with null longitude', () => {
      const points = [
        { latitude: 37.5, longitude: -122.0, altitude: 1000 },
        { latitude: 37.5, longitude: null, altitude: 1000 },
      ];
      const result = filterValidTrajectoryPoints(points);
      expect(result).toHaveLength(1);
    });

    it('keeps points with null altitude', () => {
      const points = [
        { latitude: 37.5, longitude: -122.0, altitude: null },
      ];
      const result = filterValidTrajectoryPoints(points);
      expect(result).toHaveLength(1);
    });

    it('returns empty array for all invalid points', () => {
      const points = [
        { latitude: null, longitude: -122.0, altitude: 1000 },
        { latitude: 37.5, longitude: null, altitude: 1000 },
      ];
      const result = filterValidTrajectoryPoints(points);
      expect(result).toHaveLength(0);
    });
  });

  describe('calculateTrajectoryColor', () => {
    it('returns lighter color for first point', () => {
      const color = calculateTrajectoryColor(0, 10);
      expect(color.r).toBeCloseTo(0.2, 2);
      expect(color.g).toBeCloseTo(0.4, 2);
      expect(color.b).toBeCloseTo(0.8, 2);
    });

    it('returns brighter color for last point', () => {
      const color = calculateTrajectoryColor(9, 10);
      expect(color.r).toBeCloseTo(0.3, 2);
      expect(color.g).toBeCloseTo(0.6, 2);
      expect(color.b).toBeCloseTo(1.0, 2);
    });

    it('interpolates middle points', () => {
      const first = calculateTrajectoryColor(0, 10);
      const middle = calculateTrajectoryColor(5, 10);
      const last = calculateTrajectoryColor(9, 10);

      expect(middle.r).toBeGreaterThan(first.r);
      expect(middle.r).toBeLessThan(last.r);
    });

    it('handles single point', () => {
      const color = calculateTrajectoryColor(0, 1);
      expect(color.r).toBeCloseTo(0.2, 2);
    });
  });

  describe('samplePointIndices', () => {
    it('returns all indices when total <= target', () => {
      const result = samplePointIndices(5, 10);
      expect(result).toEqual([0, 1, 2, 3, 4]);
    });

    it('samples at intervals when total > target', () => {
      const result = samplePointIndices(30, 10);
      expect(result.length).toBeLessThanOrEqual(15);
      expect(result[0]).toBe(0); // Always includes first
    });

    it('returns correct interval spacing', () => {
      const result = samplePointIndices(100, 10);
      const interval = result[1] - result[0];
      expect(interval).toBe(10); // 100/10 = 10
    });

    it('handles exact divisibility', () => {
      const result = samplePointIndices(20, 5);
      expect(result).toEqual([0, 4, 8, 12, 16]);
    });
  });

  // ========================================================================
  // Runway & Taxiway Geometry
  // ========================================================================
  describe('calculateRunwayGeometry', () => {
    it('calculates horizontal runway length', () => {
      const geom = calculateRunwayGeometry(
        { x: 0, z: 0 },
        { x: 100, z: 0 }
      );
      expect(geom.length).toBeCloseTo(100, 5);
    });

    it('calculates diagonal runway length', () => {
      const geom = calculateRunwayGeometry(
        { x: 0, z: 0 },
        { x: 30, z: 40 }
      );
      expect(geom.length).toBeCloseTo(50, 5); // 3-4-5 triangle
    });

    it('calculates center position', () => {
      const geom = calculateRunwayGeometry(
        { x: 10, z: 20 },
        { x: 50, z: 80 }
      );
      expect(geom.centerX).toBe(30);
      expect(geom.centerZ).toBe(50);
    });

    it('calculates angle for east-west runway', () => {
      const geom = calculateRunwayGeometry(
        { x: 0, z: 0 },
        { x: 100, z: 0 }
      );
      expect(geom.angle).toBeCloseTo(0, 5);
    });

    it('calculates angle for north-south runway', () => {
      const geom = calculateRunwayGeometry(
        { x: 0, z: 0 },
        { x: 0, z: 100 }
      );
      expect(geom.angle).toBeCloseTo(Math.PI / 2, 5);
    });
  });

  describe('generateRunwayMarkings', () => {
    it('generates markings for runway', () => {
      const markings = generateRunwayMarkings(500);
      expect(markings.length).toBeGreaterThan(0);
    });

    it('respects end buffer', () => {
      const markings = generateRunwayMarkings(500, 30, 20, 40);
      const totalLength = 500 - 40;
      markings.forEach(m => {
        expect(Math.abs(m.x)).toBeLessThanOrEqual(totalLength / 2 + 30);
      });
    });

    it('spaces markings at correct intervals', () => {
      const markingLength = 30;
      const gapLength = 20;
      const markings = generateRunwayMarkings(1000, markingLength, gapLength);

      if (markings.length >= 2) {
        const spacing = markings[1].x - markings[0].x;
        expect(spacing).toBeCloseTo(markingLength + gapLength, 1);
      }
    });

    it('returns empty array for very short runway', () => {
      const markings = generateRunwayMarkings(30, 30, 20, 40);
      expect(markings.length).toBeLessThanOrEqual(1);
    });
  });

  describe('generateThresholdStripes', () => {
    it('generates stripes across runway width', () => {
      const stripes = generateThresholdStripes(45);
      expect(stripes.length).toBeGreaterThan(0);
    });

    it('centers stripes around zero', () => {
      const stripes = generateThresholdStripes(45);
      const sum = stripes.reduce((a, b) => a + b, 0);
      expect(sum / stripes.length).toBeCloseTo(0, 1);
    });

    it('respects margin parameter', () => {
      const stripesSmallMargin = generateThresholdStripes(45, 3, 3, 5);
      const stripesLargeMargin = generateThresholdStripes(45, 3, 3, 20);
      expect(stripesSmallMargin.length).toBeGreaterThan(stripesLargeMargin.length);
    });
  });

  describe('calculateTaxiwaySegment', () => {
    it('calculates segment geometry same as runway', () => {
      const start = { x: 10, z: 20 };
      const end = { x: 50, z: 60 };

      const taxiway = calculateTaxiwaySegment(start, end);
      const runway = calculateRunwayGeometry(start, end);

      expect(taxiway.length).toBe(runway.length);
      expect(taxiway.centerX).toBe(runway.centerX);
      expect(taxiway.angle).toBe(runway.angle);
    });
  });

  // ========================================================================
  // Airline Utilities
  // ========================================================================
  describe('extractAirlineCode', () => {
    it('extracts first 3 characters', () => {
      expect(extractAirlineCode('UAL123')).toBe('UAL');
    });

    it('converts to uppercase', () => {
      expect(extractAirlineCode('ual123')).toBe('UAL');
    });

    it('returns null for null callsign', () => {
      expect(extractAirlineCode(null)).toBeNull();
    });

    it('returns null for short callsign', () => {
      expect(extractAirlineCode('UA')).toBeNull();
    });

    it('handles exactly 3 characters', () => {
      expect(extractAirlineCode('UAL')).toBe('UAL');
    });
  });

  describe('getMeshColorType', () => {
    it('identifies tail meshes', () => {
      expect(getMeshColorType('vertical_tail')).toBe('tail');
      expect(getMeshColorType('Tail_Fin')).toBe('tail');
      expect(getMeshColorType('Logo_Area')).toBe('tail');
    });

    it('identifies fuselage meshes', () => {
      expect(getMeshColorType('main_fuselage')).toBe('fuselage');
      expect(getMeshColorType('Body_Section')).toBe('fuselage');
    });

    it('identifies engine meshes', () => {
      expect(getMeshColorType('left_engine')).toBe('engine');
      expect(getMeshColorType('Landing_Gear')).toBe('engine');
      expect(getMeshColorType('front_wheel')).toBe('engine');
    });

    it('identifies window meshes', () => {
      expect(getMeshColorType('passenger_windows')).toBe('window');
      expect(getMeshColorType('Cockpit_Glass')).toBe('window');
    });

    it('returns default for unknown meshes', () => {
      expect(getMeshColorType('wing_section')).toBe('default');
      expect(getMeshColorType('random_part')).toBe('default');
    });
  });

  // ========================================================================
  // Distance Utilities
  // ========================================================================
  describe('distanceSquared', () => {
    it('returns 0 for same position', () => {
      const pos = { x: 10, y: 20, z: 30 };
      expect(distanceSquared(pos, pos)).toBe(0);
    });

    it('calculates squared distance correctly', () => {
      const a = { x: 0, y: 0, z: 0 };
      const b = { x: 3, y: 4, z: 0 };
      expect(distanceSquared(a, b)).toBe(25); // 3² + 4² = 25
    });

    it('works in 3D', () => {
      const a = { x: 0, y: 0, z: 0 };
      const b = { x: 1, y: 2, z: 2 };
      expect(distanceSquared(a, b)).toBe(9); // 1² + 2² + 2² = 9
    });
  });

  describe('hasPositionChanged', () => {
    it('returns false for same position', () => {
      const pos = { x: 10, y: 20, z: 30 };
      expect(hasPositionChanged(pos, pos)).toBe(false);
    });

    it('returns false for change below threshold', () => {
      const a = { x: 0, y: 0, z: 0 };
      const b = { x: 0.001, y: 0, z: 0 };
      expect(hasPositionChanged(a, b, 0.01)).toBe(false);
    });

    it('returns true for change above threshold', () => {
      const a = { x: 0, y: 0, z: 0 };
      const b = { x: 1, y: 0, z: 0 };
      expect(hasPositionChanged(a, b, 0.01)).toBe(true);
    });

    it('uses default threshold', () => {
      const a = { x: 0, y: 0, z: 0 };
      const b = { x: 0.02, y: 0, z: 0 };
      expect(hasPositionChanged(a, b)).toBe(true);
    });
  });

  describe('hasRotationChanged', () => {
    it('returns false for same rotation', () => {
      expect(hasRotationChanged(1.5, 1.5)).toBe(false);
    });

    it('returns false for change below threshold', () => {
      expect(hasRotationChanged(0, 0.00001, 0.0001)).toBe(false);
    });

    it('returns true for change above threshold', () => {
      expect(hasRotationChanged(0, 0.1, 0.0001)).toBe(true);
    });
  });
});
