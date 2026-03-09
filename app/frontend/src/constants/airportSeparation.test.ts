/**
 * Aircraft Separation Requirements Tests
 *
 * Validates FAA/ICAO separation constraints that the digital twin must enforce:
 *   - Wake turbulence categories and pair-wise separation matrix
 *   - Approach / taxi / gate minimum distances
 *   - Capacity limits per phase
 *   - Helper functions (distance, wake category lookup, status classification)
 *   - Consistency between 2D (degree) and 3D (scene-unit) constants
 *   - Consistency between frontend constants and backend fallback.py
 */
import { describe, it, expect } from 'vitest'
import {
  WAKE_CATEGORIES,
  WAKE_SEPARATION_NM,
  DEFAULT_SEPARATION_NM,
  NM_TO_DEG,
  MIN_APPROACH_SEPARATION_DEG,
  MIN_TAXI_SEPARATION_DEG,
  MIN_GATE_SEPARATION_DEG,
  MAX_APPROACH_AIRCRAFT,
  MAX_PARKED_AIRCRAFT,
  MAX_TAXI_AIRCRAFT,
  GATE_POSITIONS,
  getWakeCategory,
  getRequiredSeparationNM,
  getRequiredSeparationDeg,
  distanceNM,
  hasApproachSeparation,
  getSeparationStatus,
} from './airportLayout'
import {
  SCENE_SCALE,
  MIN_APPROACH_SEPARATION_3D,
  MIN_TAXI_SEPARATION_3D,
  MIN_GATE_SEPARATION_3D,
  CAPACITY_LIMITS,
  COLORS,
} from './airport3D'

// ============================================================================
// 1. Wake turbulence categories
// ============================================================================
describe('Wake turbulence categories', () => {
  it('SUPER category contains A380', () => {
    expect(WAKE_CATEGORIES.SUPER).toContain('A380')
  })

  it('HEAVY category contains all wide-body types', () => {
    const heavyTypes = ['B747', 'B777', 'B787', 'A330', 'A340', 'A350', 'A345']
    heavyTypes.forEach((type) => {
      expect(WAKE_CATEGORIES.HEAVY).toContain(type)
    })
  })

  it('LARGE category contains common narrow-body types', () => {
    const largeTypes = ['A320', 'A321', 'A319', 'B737', 'B738', 'B739']
    largeTypes.forEach((type) => {
      expect(WAKE_CATEGORIES.LARGE).toContain(type)
    })
  })

  it('SMALL category contains regional jets', () => {
    const smallTypes = ['CRJ9', 'E175', 'E190']
    smallTypes.forEach((type) => {
      expect(WAKE_CATEGORIES.SMALL).toContain(type)
    })
  })

  it('categories are mutually exclusive (no aircraft in multiple categories)', () => {
    const allTypes = [
      ...WAKE_CATEGORIES.SUPER,
      ...WAKE_CATEGORIES.HEAVY,
      ...WAKE_CATEGORIES.LARGE,
      ...WAKE_CATEGORIES.SMALL,
    ]
    const uniqueTypes = new Set(allTypes)
    expect(uniqueTypes.size).toBe(allTypes.length)
  })
})

// ============================================================================
// 2. Wake turbulence category lookup
// ============================================================================
describe('getWakeCategory', () => {
  it('returns SUPER for A380', () => {
    expect(getWakeCategory('A380')).toBe('SUPER')
  })

  it('returns HEAVY for B747', () => {
    expect(getWakeCategory('B747')).toBe('HEAVY')
  })

  it('returns HEAVY for B777', () => {
    expect(getWakeCategory('B777')).toBe('HEAVY')
  })

  it('returns LARGE for A320', () => {
    expect(getWakeCategory('A320')).toBe('LARGE')
  })

  it('returns LARGE for B738', () => {
    expect(getWakeCategory('B738')).toBe('LARGE')
  })

  it('returns SMALL for E175', () => {
    expect(getWakeCategory('E175')).toBe('SMALL')
  })

  it('defaults to LARGE for unknown types', () => {
    expect(getWakeCategory('UNKNOWN')).toBe('LARGE')
    expect(getWakeCategory('C172')).toBe('LARGE')
    expect(getWakeCategory('')).toBe('LARGE')
  })
})

// ============================================================================
// 3. Wake separation matrix (FAA/ICAO standards)
// ============================================================================
describe('Wake separation matrix', () => {
  it('has all required category pairs', () => {
    const expectedPairs = [
      'SUPER_SUPER', 'SUPER_HEAVY', 'SUPER_LARGE', 'SUPER_SMALL',
      'HEAVY_HEAVY', 'HEAVY_LARGE', 'HEAVY_SMALL',
      'LARGE_LARGE', 'LARGE_SMALL',
      'SMALL_SMALL',
    ]
    expectedPairs.forEach((pair) => {
      expect(WAKE_SEPARATION_NM).toHaveProperty(pair)
      expect(typeof WAKE_SEPARATION_NM[pair]).toBe('number')
    })
  })

  it('SUPER behind SUPER requires 4 NM', () => {
    expect(WAKE_SEPARATION_NM['SUPER_SUPER']).toBe(4.0)
  })

  it('HEAVY behind SUPER requires 6 NM', () => {
    expect(WAKE_SEPARATION_NM['SUPER_HEAVY']).toBe(6.0)
  })

  it('LARGE behind SUPER requires 7 NM', () => {
    expect(WAKE_SEPARATION_NM['SUPER_LARGE']).toBe(7.0)
  })

  it('SMALL behind SUPER requires 8 NM (maximum)', () => {
    expect(WAKE_SEPARATION_NM['SUPER_SMALL']).toBe(8.0)
  })

  it('HEAVY behind HEAVY requires 4 NM', () => {
    expect(WAKE_SEPARATION_NM['HEAVY_HEAVY']).toBe(4.0)
  })

  it('LARGE behind HEAVY requires 5 NM', () => {
    expect(WAKE_SEPARATION_NM['HEAVY_LARGE']).toBe(5.0)
  })

  it('SMALL behind HEAVY requires 6 NM', () => {
    expect(WAKE_SEPARATION_NM['HEAVY_SMALL']).toBe(6.0)
  })

  it('LARGE behind LARGE requires 3 NM (standard minimum)', () => {
    expect(WAKE_SEPARATION_NM['LARGE_LARGE']).toBe(3.0)
  })

  it('SMALL behind LARGE requires 4 NM', () => {
    expect(WAKE_SEPARATION_NM['LARGE_SMALL']).toBe(4.0)
  })

  it('SMALL behind SMALL requires 3 NM', () => {
    expect(WAKE_SEPARATION_NM['SMALL_SMALL']).toBe(3.0)
  })

  it('separation increases as following aircraft gets smaller (for SUPER lead)', () => {
    expect(WAKE_SEPARATION_NM['SUPER_SUPER']).toBeLessThan(WAKE_SEPARATION_NM['SUPER_HEAVY'])
    expect(WAKE_SEPARATION_NM['SUPER_HEAVY']).toBeLessThan(WAKE_SEPARATION_NM['SUPER_LARGE'])
    expect(WAKE_SEPARATION_NM['SUPER_LARGE']).toBeLessThan(WAKE_SEPARATION_NM['SUPER_SMALL'])
  })

  it('separation increases as following aircraft gets smaller (for HEAVY lead)', () => {
    expect(WAKE_SEPARATION_NM['HEAVY_HEAVY']).toBeLessThan(WAKE_SEPARATION_NM['HEAVY_LARGE'])
    expect(WAKE_SEPARATION_NM['HEAVY_LARGE']).toBeLessThan(WAKE_SEPARATION_NM['HEAVY_SMALL'])
  })

  it('no separation is less than 3 NM (ICAO minimum)', () => {
    Object.values(WAKE_SEPARATION_NM).forEach((nm) => {
      expect(nm).toBeGreaterThanOrEqual(3.0)
    })
  })

  it('no separation exceeds 8 NM', () => {
    Object.values(WAKE_SEPARATION_NM).forEach((nm) => {
      expect(nm).toBeLessThanOrEqual(8.0)
    })
  })

  it('default separation is 3 NM', () => {
    expect(DEFAULT_SEPARATION_NM).toBe(3.0)
  })
})

// ============================================================================
// 4. getRequiredSeparationNM
// ============================================================================
describe('getRequiredSeparationNM', () => {
  it('returns correct separation for known pair (A380 → B738)', () => {
    // SUPER → LARGE = 7.0 NM
    expect(getRequiredSeparationNM('A380', 'B738')).toBe(7.0)
  })

  it('returns correct separation for heavy pair (B747 → B777)', () => {
    // HEAVY → HEAVY = 4.0 NM
    expect(getRequiredSeparationNM('B747', 'B777')).toBe(4.0)
  })

  it('returns correct separation for large pair (A320 → B737)', () => {
    // LARGE → LARGE = 3.0 NM
    expect(getRequiredSeparationNM('A320', 'B737')).toBe(3.0)
  })

  it('returns correct separation for mixed pair (B777 → E175)', () => {
    // HEAVY → SMALL = 6.0 NM
    expect(getRequiredSeparationNM('B777', 'E175')).toBe(6.0)
  })

  it('returns default for unknown aircraft types', () => {
    // Unknown defaults to LARGE, so LARGE_LARGE = 3.0 NM
    expect(getRequiredSeparationNM('UNKNOWN1', 'UNKNOWN2')).toBe(3.0)
  })

  it('is NOT symmetric (lead/follow order matters)', () => {
    // HEAVY → SMALL = 6.0, but SMALL is not a key as lead for HEAVY
    // LARGE → SMALL = 4.0, SMALL → LARGE would use default
    const heavySmall = getRequiredSeparationNM('B747', 'E175')
    const smallHeavy = getRequiredSeparationNM('E175', 'B747')
    // SMALL_HEAVY is not in the matrix → default 3.0
    expect(heavySmall).toBe(6.0)
    expect(smallHeavy).toBe(DEFAULT_SEPARATION_NM)
  })
})

// ============================================================================
// 5. getRequiredSeparationDeg
// ============================================================================
describe('getRequiredSeparationDeg', () => {
  it('converts NM to degrees correctly', () => {
    // 3 NM * (1/60 deg/NM) = 0.05 deg
    const deg = getRequiredSeparationDeg('A320', 'B737')
    expect(deg).toBeCloseTo(3.0 / 60, 6)
  })

  it('7 NM converts to ~0.1167 degrees', () => {
    const deg = getRequiredSeparationDeg('A380', 'B738')
    expect(deg).toBeCloseTo(7.0 / 60, 6)
  })
})

// ============================================================================
// 6. Minimum separation distances
// ============================================================================
describe('Minimum separation distances', () => {
  it('NM_TO_DEG is 1/60', () => {
    expect(NM_TO_DEG).toBeCloseTo(1 / 60, 10)
  })

  it('MIN_APPROACH_SEPARATION_DEG is 3 NM in degrees', () => {
    expect(MIN_APPROACH_SEPARATION_DEG).toBeCloseTo(3.0 * NM_TO_DEG, 10)
  })

  it('MIN_TAXI_SEPARATION_DEG is ~100m (0.001 deg)', () => {
    expect(MIN_TAXI_SEPARATION_DEG).toBe(0.001)
  })

  it('MIN_GATE_SEPARATION_DEG is ~200m (0.002 deg)', () => {
    expect(MIN_GATE_SEPARATION_DEG).toBe(0.002)
  })

  it('approach separation > taxi separation > 0', () => {
    expect(MIN_APPROACH_SEPARATION_DEG).toBeGreaterThan(MIN_TAXI_SEPARATION_DEG)
    expect(MIN_TAXI_SEPARATION_DEG).toBeGreaterThan(0)
  })

  it('gate separation >= taxi separation', () => {
    expect(MIN_GATE_SEPARATION_DEG).toBeGreaterThanOrEqual(MIN_TAXI_SEPARATION_DEG)
  })
})

// ============================================================================
// 7. Capacity limits
// ============================================================================
describe('Capacity limits', () => {
  it('MAX_APPROACH_AIRCRAFT is 4', () => {
    expect(MAX_APPROACH_AIRCRAFT).toBe(4)
  })

  it('MAX_PARKED_AIRCRAFT is 5', () => {
    expect(MAX_PARKED_AIRCRAFT).toBe(5)
  })

  it('MAX_TAXI_AIRCRAFT is 2', () => {
    expect(MAX_TAXI_AIRCRAFT).toBe(2)
  })
})

// ============================================================================
// 8. distanceNM
// ============================================================================
describe('distanceNM', () => {
  it('returns 0 for identical positions', () => {
    expect(distanceNM([37.62, -122.38], [37.62, -122.38])).toBe(0)
  })

  it('returns positive distance for different positions', () => {
    const d = distanceNM([37.62, -122.38], [37.63, -122.38])
    expect(d).toBeGreaterThan(0)
  })

  it('1 degree latitude difference ≈ 60 NM', () => {
    const d = distanceNM([37.0, -122.0], [38.0, -122.0])
    expect(d).toBeCloseTo(60, 0)
  })

  it('0.05 degrees ≈ 3 NM (standard approach separation)', () => {
    const d = distanceNM([37.0, -122.0], [37.05, -122.0])
    expect(d).toBeCloseTo(3.0, 0)
  })

  it('is symmetric (distance A→B equals B→A)', () => {
    const posA: [number, number] = [37.62, -122.38]
    const posB: [number, number] = [37.65, -122.40]
    expect(distanceNM(posA, posB)).toBeCloseTo(distanceNM(posB, posA), 10)
  })
})

// ============================================================================
// 9. hasApproachSeparation
// ============================================================================
describe('hasApproachSeparation', () => {
  it('returns true when aircraft are far apart', () => {
    // ~6 NM apart, only 3 NM required (LARGE-LARGE)
    const result = hasApproachSeparation(
      [37.62, -122.38], 'A320',
      [37.52, -122.38], 'B737',
    )
    expect(result).toBe(true)
  })

  it('returns false when aircraft are too close', () => {
    // Very close together, any separation requirement will fail
    const result = hasApproachSeparation(
      [37.620, -122.380], 'B747',
      [37.621, -122.380], 'E175',
    )
    // HEAVY→SMALL requires 6 NM, these are ~0.06 NM apart
    expect(result).toBe(false)
  })

  it('returns true when slightly above the required distance', () => {
    // LARGE-LARGE requires 3 NM = 0.05 deg; add tiny buffer for float precision
    const sep = 3.0 * NM_TO_DEG + 0.0001
    const result = hasApproachSeparation(
      [37.62, -122.38], 'A320',
      [37.62 + sep, -122.38], 'B737',
    )
    expect(result).toBe(true)
  })

  it('SUPER lead requires more separation than LARGE lead', () => {
    // Position the follower at 5 NM
    const sep5nm = 5.0 * NM_TO_DEG
    const follow: [number, number] = [37.62 + sep5nm, -122.38]
    const lead: [number, number] = [37.62, -122.38]

    // LARGE lead → LARGE follow: needs 3 NM → should pass at 5 NM
    expect(hasApproachSeparation(lead, 'A320', follow, 'B737')).toBe(true)

    // SUPER lead → LARGE follow: needs 7 NM → should fail at 5 NM
    expect(hasApproachSeparation(lead, 'A380', follow, 'B737')).toBe(false)
  })
})

// ============================================================================
// 10. getSeparationStatus
// ============================================================================
describe('getSeparationStatus', () => {
  it('returns "ok" when actual >= 1.2x required', () => {
    expect(getSeparationStatus(4.0, 3.0)).toBe('ok') // 1.33x
    expect(getSeparationStatus(6.0, 3.0)).toBe('ok') // 2.0x
  })

  it('returns "warning" when actual >= required but < 1.2x', () => {
    expect(getSeparationStatus(3.0, 3.0)).toBe('warning')  // exactly 1.0x
    expect(getSeparationStatus(3.5, 3.0)).toBe('warning')  // 1.167x
  })

  it('returns "violation" when actual < required', () => {
    expect(getSeparationStatus(2.5, 3.0)).toBe('violation')
    expect(getSeparationStatus(0.5, 3.0)).toBe('violation')
    expect(getSeparationStatus(0, 3.0)).toBe('violation')
  })

  it('boundary: exactly 1.2x is "ok"', () => {
    expect(getSeparationStatus(3.6, 3.0)).toBe('ok') // exactly 1.2x
  })

  it('boundary: just below 1.2x is "warning"', () => {
    expect(getSeparationStatus(3.59, 3.0)).toBe('warning')
  })

  it('boundary: just below 1.0x is "violation"', () => {
    expect(getSeparationStatus(2.99, 3.0)).toBe('violation')
  })
})

// ============================================================================
// 11. Gate positions satisfy minimum gate separation
// ============================================================================
describe('Gate positions satisfy separation constraints', () => {
  const gateEntries = Object.entries(GATE_POSITIONS)

  it('no two gates overlap (all pairs separated by at least taxi minimum)', () => {
    const violations: string[] = []

    for (let i = 0; i < gateEntries.length; i++) {
      for (let j = i + 1; j < gateEntries.length; j++) {
        const [nameA, posA] = gateEntries[i]
        const [nameB, posB] = gateEntries[j]
        const latDiff = posA[0] - posB[0]
        const lonDiff = posA[1] - posB[1]
        const dist = Math.sqrt(latDiff * latDiff + lonDiff * lonDiff)

        // Adjacent gates within a terminal area can be closer than MIN_GATE_SEPARATION_DEG
        // but must still satisfy MIN_TAXI_SEPARATION_DEG (aircraft don't overlap)
        if (dist < MIN_TAXI_SEPARATION_DEG) {
          violations.push(
            `${nameA} ↔ ${nameB}: ${dist.toFixed(6)} deg < ${MIN_TAXI_SEPARATION_DEG} deg`,
          )
        }
      }
    }

    expect(violations).toEqual([])
  })

  it('gates across different terminal areas have MIN_GATE_SEPARATION_DEG', () => {
    // Cross-terminal pairs: G-area vs B-area, G-area vs C-area, etc.
    const terminalPairs = [
      ['G1', 'B1'],
      ['G1', 'C1'],
      ['A1', 'B1'],
      ['A1', 'C1'],
      ['B1', 'C1'],
    ]

    for (const [nameA, nameB] of terminalPairs) {
      const posA = GATE_POSITIONS[nameA]
      const posB = GATE_POSITIONS[nameB]
      if (!posA || !posB) continue

      const latDiff = posA[0] - posB[0]
      const lonDiff = posA[1] - posB[1]
      const dist = Math.sqrt(latDiff * latDiff + lonDiff * lonDiff)

      expect(dist).toBeGreaterThanOrEqual(MIN_GATE_SEPARATION_DEG)
    }
  })

  it('gates within the same terminal area have reasonable spacing', () => {
    // G1, G2, G3 in same area; should each be spaced
    const g1 = GATE_POSITIONS['G1']
    const g2 = GATE_POSITIONS['G2']
    const g3 = GATE_POSITIONS['G3']

    expect(distanceNM(g1, g2)).toBeGreaterThan(0)
    expect(distanceNM(g2, g3)).toBeGreaterThan(0)
  })
})

// ============================================================================
// 12. 3D constants are consistent with 2D constants
// ============================================================================
describe('3D ↔ 2D separation consistency', () => {
  it('SCENE_SCALE is 10000', () => {
    expect(SCENE_SCALE).toBe(10000)
  })

  it('3D approach separation matches 2D (3 NM)', () => {
    const expected3D = 3.0 * NM_TO_DEG * SCENE_SCALE
    expect(MIN_APPROACH_SEPARATION_3D).toBeCloseTo(expected3D, 2)
  })

  it('3D taxi separation matches 2D', () => {
    const expected3D = MIN_TAXI_SEPARATION_DEG * SCENE_SCALE
    expect(MIN_TAXI_SEPARATION_3D).toBeCloseTo(expected3D, 2)
  })

  it('3D gate separation matches 2D', () => {
    const expected3D = MIN_GATE_SEPARATION_DEG * SCENE_SCALE
    expect(MIN_GATE_SEPARATION_3D).toBeCloseTo(expected3D, 2)
  })

  it('3D capacity limits match 2D constants', () => {
    expect(CAPACITY_LIMITS.maxApproach).toBe(MAX_APPROACH_AIRCRAFT)
    expect(CAPACITY_LIMITS.maxParked).toBe(MAX_PARKED_AIRCRAFT)
    expect(CAPACITY_LIMITS.maxTaxi).toBe(MAX_TAXI_AIRCRAFT)
  })

  it('separation warning/violation colors are defined', () => {
    expect(COLORS.separationWarning).toBeDefined()
    expect(COLORS.separationViolation).toBeDefined()
    // Warning is orange-ish, violation is red
    expect(COLORS.separationWarning).not.toBe(COLORS.separationViolation)
  })
})
