import { describe, it, expect } from 'vitest';
import { distSq, splitAtGaps, perpendicularDist, simplify, chaikinSmooth } from './TrajectoryLine';

describe('distSq', () => {
  it('returns 0 for same point', () => {
    expect(distSq(37.6, -122.4, 37.6, -122.4)).toBe(0);
  });

  it('returns correct squared distance', () => {
    const result = distSq(0, 0, 3, 4);
    expect(result).toBe(25); // 3² + 4² = 25
  });

  it('is symmetric', () => {
    expect(distSq(1, 2, 3, 4)).toBe(distSq(3, 4, 1, 2));
  });
});

describe('splitAtGaps', () => {
  it('returns single segment when no gaps', () => {
    const points: [number, number][] = [
      [37.600, -122.400],
      [37.601, -122.401],
      [37.602, -122.402],
      [37.603, -122.403],
    ];
    const segments = splitAtGaps(points);
    expect(segments).toHaveLength(1);
    expect(segments[0]).toHaveLength(4);
  });

  it('splits at large gap', () => {
    const points: [number, number][] = [
      [37.600, -122.400],
      [37.601, -122.401],
      // gap > 0.04° here
      [37.700, -122.500],
      [37.701, -122.501],
    ];
    const segments = splitAtGaps(points);
    expect(segments).toHaveLength(2);
    expect(segments[0]).toHaveLength(2);
    expect(segments[1]).toHaveLength(2);
  });

  it('handles multiple gaps', () => {
    const points: [number, number][] = [
      [37.600, -122.400],
      [37.601, -122.401],
      [37.800, -122.600], // gap 1
      [37.801, -122.601],
      [38.000, -122.800], // gap 2
      [38.001, -122.801],
    ];
    const segments = splitAtGaps(points);
    expect(segments).toHaveLength(3);
  });

  it('returns empty array for empty input', () => {
    expect(splitAtGaps([])).toEqual([]);
  });

  it('returns single-element array for single point', () => {
    const segments = splitAtGaps([[37.6, -122.4]]);
    // Implementation wraps single point in an array
    expect(segments).toHaveLength(1);
    expect(segments[0]).toEqual([[37.6, -122.4]]);
  });

  it('returns empty when two points are far apart (gap splits them into single-point segments)', () => {
    const points: [number, number][] = [
      [37.600, -122.400],
      [37.800, -122.600], // far apart
    ];
    const segments = splitAtGaps(points);
    // Neither single-point segment qualifies (length < 2)
    expect(segments).toHaveLength(0);
  });
});

describe('perpendicularDist', () => {
  it('returns 0 for point on line', () => {
    const start: [number, number] = [0, 0];
    const end: [number, number] = [10, 0];
    const point: [number, number] = [5, 0]; // on the line
    expect(perpendicularDist(point, start, end)).toBeCloseTo(0);
  });

  it('returns correct perpendicular distance', () => {
    const start: [number, number] = [0, 0];
    const end: [number, number] = [10, 0];
    const point: [number, number] = [5, 3]; // 3 units above midpoint
    expect(perpendicularDist(point, start, end)).toBeCloseTo(3);
  });

  it('handles degenerate line (zero length) — returns euclidean distance', () => {
    const start: [number, number] = [5, 5];
    const end: [number, number] = [5, 5]; // same point
    const point: [number, number] = [8, 9];
    const expected = Math.sqrt((8 - 5) ** 2 + (9 - 5) ** 2); // 5
    expect(perpendicularDist(point, start, end)).toBeCloseTo(expected);
  });

  it('clamps projection to segment endpoints', () => {
    const start: [number, number] = [0, 0];
    const end: [number, number] = [10, 0];
    const point: [number, number] = [-5, 3]; // beyond start
    // Closest point on segment is (0,0), distance is sqrt(25+9) = sqrt(34)
    expect(perpendicularDist(point, start, end)).toBeCloseTo(Math.sqrt(34));
  });
});

describe('simplify (Douglas-Peucker)', () => {
  it('returns just endpoints for a straight line', () => {
    const points: [number, number][] = [
      [0, 0], [1, 1], [2, 2], [3, 3], [4, 4],
    ];
    const result = simplify(points, 0.0001);
    expect(result).toHaveLength(2);
    expect(result[0]).toEqual([0, 0]);
    expect(result[1]).toEqual([4, 4]);
  });

  it('preserves vertices of a zigzag above epsilon', () => {
    const points: [number, number][] = [
      [0, 0], [1, 1], [2, 0], [3, 1], [4, 0],
    ];
    const result = simplify(points, 0.1);
    // The zigzag deviations (1 unit) exceed epsilon (0.1), so all vertices kept
    expect(result.length).toBeGreaterThanOrEqual(4);
  });

  it('returns input unchanged for < 3 points', () => {
    const two: [number, number][] = [[0, 0], [1, 1]];
    expect(simplify(two)).toEqual(two);

    const one: [number, number][] = [[5, 5]];
    expect(simplify(one)).toEqual(one);
  });

  it('reduces noise below epsilon', () => {
    // Points with tiny deviations (0.00001) from a straight line
    const points: [number, number][] = [
      [0, 0], [1, 0.00001], [2, -0.00001], [3, 0.00001], [4, 0],
    ];
    const result = simplify(points, 0.001);
    expect(result).toHaveLength(2); // just endpoints
  });
});

describe('chaikinSmooth', () => {
  it('returns input for < 3 points', () => {
    const two: [number, number][] = [[0, 0], [1, 1]];
    expect(chaikinSmooth(two)).toEqual(two);

    const one: [number, number][] = [[5, 5]];
    expect(chaikinSmooth(one)).toEqual(one);
  });

  it('increases point count for a triangle', () => {
    const triangle: [number, number][] = [[0, 0], [5, 10], [10, 0]];
    const smoothed = chaikinSmooth(triangle, 1);
    // 1 iteration: first + 2*(n-1) midpoints + last = 1 + 4 + 1 = 6
    expect(smoothed.length).toBeGreaterThan(triangle.length);
  });

  it('preserves first and last points', () => {
    const points: [number, number][] = [[0, 0], [5, 10], [10, 0], [15, 5]];
    const smoothed = chaikinSmooth(points, 3);
    expect(smoothed[0]).toEqual([0, 0]);
    expect(smoothed[smoothed.length - 1]).toEqual([15, 5]);
  });

  it('with iterations=0 returns same points', () => {
    const points: [number, number][] = [[0, 0], [5, 10], [10, 0]];
    const result = chaikinSmooth(points, 0);
    expect(result).toEqual(points);
  });

  it('smoothed points stay within convex hull of original', () => {
    const points: [number, number][] = [[0, 0], [5, 10], [10, 0]];
    const smoothed = chaikinSmooth(points, 3);
    for (const [lat, lon] of smoothed) {
      expect(lat).toBeGreaterThanOrEqual(0);
      expect(lat).toBeLessThanOrEqual(10);
      expect(lon).toBeGreaterThanOrEqual(0);
      expect(lon).toBeLessThanOrEqual(10);
    }
  });
});
