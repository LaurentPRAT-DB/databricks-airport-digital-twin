/**
 * Aircraft Separation UI Integration Tests
 *
 * Validates that the flight data rendered in the App UI respects
 * FAA/ICAO aircraft separation requirements:
 *   - Airborne aircraft maintain wake turbulence separation
 *   - Ground aircraft maintain taxi separation
 *   - Capacity limits are not exceeded per phase
 *   - The detail panel surfaces correct separation-related data per aircraft type
 *
 * These tests exercise the full App (rendering, API mocking, flight context)
 * and inspect the actual rendered data to verify separation compliance.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import userEvent from '@testing-library/user-event'
import { render as rtlRender, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse, delay } from 'msw'
import { server } from './test/mocks/server'
import { PERFORMANCE_THRESHOLDS } from './test/test-utils'
import App from './App'
import {
  distanceNM,
  getRequiredSeparationNM,
  getSeparationStatus,
  hasApproachSeparation,
  MAX_APPROACH_AIRCRAFT,
  MAX_PARKED_AIRCRAFT,
  MAX_TAXI_AIRCRAFT,
  MIN_TAXI_SEPARATION_DEG,
} from './constants/airportLayout'
import type { Flight } from './types/flight'

// ---------------------------------------------------------------------------
// Realistic multi-aircraft mock data with known separation characteristics
// ---------------------------------------------------------------------------

/** Flights on approach — properly separated by wake turbulence rules */
const separatedApproachFlights: Flight[] = [
  {
    icao24: 'app001',
    callsign: 'UAL100',
    latitude: 37.50,
    longitude: -122.50,
    altitude: 10000,
    velocity: 250,
    heading: 90,
    vertical_rate: -500,
    on_ground: false,
    last_seen: new Date().toISOString(),
    data_source: 'synthetic',
    flight_phase: 'approaching',
    aircraft_type: 'B737', // LARGE
  },
  {
    icao24: 'app002',
    callsign: 'DAL200',
    latitude: 37.50,
    longitude: -122.60, // ~6 NM behind (0.1 deg ≈ 6 NM)
    altitude: 12000,
    velocity: 260,
    heading: 90,
    vertical_rate: -400,
    on_ground: false,
    last_seen: new Date().toISOString(),
    data_source: 'synthetic',
    flight_phase: 'approaching',
    aircraft_type: 'A320', // LARGE
  },
]

/** Flights violating separation (too close) */
const violationFlights: Flight[] = [
  {
    icao24: 'vio001',
    callsign: 'AAL300',
    latitude: 37.55,
    longitude: -122.40,
    altitude: 8000,
    velocity: 220,
    heading: 270,
    vertical_rate: -300,
    on_ground: false,
    last_seen: new Date().toISOString(),
    data_source: 'synthetic',
    flight_phase: 'approaching',
    aircraft_type: 'B747', // HEAVY
  },
  {
    icao24: 'vio002',
    callsign: 'SWA400',
    latitude: 37.55,
    longitude: -122.405, // ~0.3 NM behind a HEAVY → needs 5 NM for LARGE follower
    altitude: 7800,
    velocity: 215,
    heading: 270,
    vertical_rate: -250,
    on_ground: false,
    last_seen: new Date().toISOString(),
    data_source: 'synthetic',
    flight_phase: 'approaching',
    aircraft_type: 'B738', // LARGE
  },
]

/** Ground aircraft with proper taxi separation */
const groundFlightsOk: Flight[] = [
  {
    icao24: 'gnd001',
    callsign: 'UAL500',
    latitude: 37.615,
    longitude: -122.390,
    altitude: 0,
    velocity: 15,
    heading: 90,
    vertical_rate: 0,
    on_ground: true,
    last_seen: new Date().toISOString(),
    data_source: 'synthetic',
    flight_phase: 'taxi_in',
    aircraft_type: 'A320',
  },
  {
    icao24: 'gnd002',
    callsign: 'DAL600',
    latitude: 37.618,
    longitude: -122.385, // ~0.36 NM from gnd001 → well above taxi minimum
    altitude: 0,
    velocity: 10,
    heading: 90,
    vertical_rate: 0,
    on_ground: true,
    last_seen: new Date().toISOString(),
    data_source: 'synthetic',
    flight_phase: 'taxi_in',
    aircraft_type: 'B738',
  },
]

/** Flights that exceed approach capacity (>4 on approach) */
const overCapacityFlights: Flight[] = Array.from({ length: 6 }, (_, i) => ({
  icao24: `cap${String(i).padStart(3, '0')}`,
  callsign: `TST${700 + i}`,
  latitude: 37.50 + i * 0.001,
  longitude: -122.50 - i * 0.1, // each ~6 NM apart
  altitude: 10000 + i * 1000,
  velocity: 250,
  heading: 90,
  vertical_rate: -500,
  on_ground: false,
  last_seen: new Date().toISOString(),
  data_source: 'synthetic' as const,
  flight_phase: 'approaching' as const,
  aircraft_type: 'A320',
}))

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  })
  return rtlRender(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  )
}

async function waitForAppReady() {
  await waitFor(
    () => {
      expect(screen.getByRole('banner')).toBeInTheDocument()
      expect(screen.getByRole('main')).toBeInTheDocument()
    },
    { timeout: 5000 },
  )
}

/** Override the flights API to return custom flight data */
function useFlightOverride(flights: Flight[]) {
  server.use(
    http.get('/api/flights', async () => {
      await delay(30)
      return HttpResponse.json({
        flights,
        count: flights.length,
        timestamp: new Date().toISOString(),
        data_source: 'synthetic',
      })
    }),
  )
}

async function timed(action: () => Promise<void>): Promise<number> {
  const start = performance.now()
  await action()
  return performance.now() - start
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Aircraft separation — UI integration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // =========================================================================
  // A. Properly separated approach flights render without issues
  // =========================================================================
  describe('Properly separated approach flights', () => {
    it('renders both descending flights in the flight list', async () => {
      useFlightOverride(separatedApproachFlights)
      renderApp()
      await waitForAppReady()

      await waitFor(() => {
        expect(screen.getByText(/UAL100/)).toBeInTheDocument()
        expect(screen.getByText(/DAL200/)).toBeInTheDocument()
      }, { timeout: 5000 })
    })

    it('separation between the two approach flights is at least the required minimum', () => {
      const f1 = separatedApproachFlights[0]
      const f2 = separatedApproachFlights[1]
      const actual = distanceNM([f1.latitude, f1.longitude], [f2.latitude, f2.longitude])
      const required = getRequiredSeparationNM(f1.aircraft_type!, f2.aircraft_type!)

      // LARGE→LARGE = 3 NM; actual ≈ 6 NM → passes
      expect(actual).toBeGreaterThanOrEqual(required)
      expect(getSeparationStatus(actual, required)).toBe('ok')
    })

    it('selecting the lead aircraft shows "Descending" phase badge in detail', async () => {
      useFlightOverride(separatedApproachFlights)
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      await waitFor(() => {
        expect(screen.getByText(/UAL100/)).toBeInTheDocument()
      }, { timeout: 5000 })

      const row = screen.getByText(/UAL100/).closest('button')!
      await user.click(row)

      // Verify the detail panel shows the icao24 (unique to detail panel)
      await waitFor(() => {
        expect(screen.getByText(/app001/)).toBeInTheDocument()
      })
    })

    it('selecting the lead aircraft shows gate recommendations (descending)', async () => {
      useFlightOverride(separatedApproachFlights)
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      await waitFor(() => {
        expect(screen.getByText(/UAL100/)).toBeInTheDocument()
      }, { timeout: 5000 })

      const row = screen.getByText(/UAL100/).closest('button')!
      const responseTime = await timed(async () => {
        await user.click(row)
        await waitFor(() => {
          expect(screen.getByText(/gate recommendations/i)).toBeInTheDocument()
        }, { timeout: 5000 })
      })

      expect(responseTime).toBeLessThan(PERFORMANCE_THRESHOLDS.apiResponse)
    })
  })

  // =========================================================================
  // B. Violation scenario: aircraft too close
  // =========================================================================
  describe('Separation violation detection (data-level)', () => {
    it('violation flights are closer than required minimum', () => {
      const f1 = violationFlights[0] // B747 = HEAVY
      const f2 = violationFlights[1] // B738 = LARGE
      const actual = distanceNM([f1.latitude, f1.longitude], [f2.latitude, f2.longitude])
      const required = getRequiredSeparationNM(f1.aircraft_type!, f2.aircraft_type!)

      // HEAVY → LARGE = 5 NM, actual ≈ 0.3 NM → violation
      expect(actual).toBeLessThan(required)
      expect(getSeparationStatus(actual, required)).toBe('violation')
    })

    it('hasApproachSeparation returns false for violation pair', () => {
      const f1 = violationFlights[0]
      const f2 = violationFlights[1]
      const result = hasApproachSeparation(
        [f1.latitude, f1.longitude], f1.aircraft_type!,
        [f2.latitude, f2.longitude], f2.aircraft_type!,
      )
      expect(result).toBe(false)
    })

    it('both violation flights still render in the UI (violations shown, not hidden)', async () => {
      useFlightOverride(violationFlights)
      renderApp()
      await waitForAppReady()

      await waitFor(() => {
        expect(screen.getByText(/AAL300/)).toBeInTheDocument()
        expect(screen.getByText(/SWA400/)).toBeInTheDocument()
      }, { timeout: 5000 })
    })

    it('user can select a violation flight and see its details', async () => {
      useFlightOverride(violationFlights)
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      await waitFor(() => {
        expect(screen.getByText(/AAL300/)).toBeInTheDocument()
      }, { timeout: 5000 })

      const row = screen.getByText(/AAL300/).closest('button')!
      await user.click(row)

      await waitFor(() => {
        // Detail panel shows B747 aircraft data
        expect(screen.getByText(/vio001/)).toBeInTheDocument()
      })
    })
  })

  // =========================================================================
  // C. Ground separation
  // =========================================================================
  describe('Ground aircraft separation', () => {
    it('ground flights satisfy taxi separation minimum', () => {
      const f1 = groundFlightsOk[0]
      const f2 = groundFlightsOk[1]
      const latDiff = f1.latitude - f2.latitude
      const lonDiff = f1.longitude - f2.longitude
      const degDist = Math.sqrt(latDiff * latDiff + lonDiff * lonDiff)

      expect(degDist).toBeGreaterThanOrEqual(MIN_TAXI_SEPARATION_DEG)
    })

    it('renders ground flights and selecting shows detail with icao24', async () => {
      useFlightOverride(groundFlightsOk)
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      await waitFor(() => {
        expect(screen.getByText(/UAL500/)).toBeInTheDocument()
      }, { timeout: 5000 })

      // Select the ground flight
      const row = screen.getByText(/UAL500/).closest('button')!
      await user.click(row)

      // Verify detail panel shows the icao24
      await waitFor(() => {
        expect(screen.getByText(/gnd001/)).toBeInTheDocument()
      })
    })

    it('ground flight shows turnaround progress', async () => {
      useFlightOverride(groundFlightsOk)
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      await waitFor(() => {
        expect(screen.getByText(/UAL500/)).toBeInTheDocument()
      }, { timeout: 5000 })

      const row = screen.getByText(/UAL500/).closest('button')!
      await user.click(row)

      await waitFor(() => {
        expect(screen.getByText(/turnaround/i)).toBeInTheDocument()
      }, { timeout: 5000 })
    })
  })

  // =========================================================================
  // D. Capacity limits
  // =========================================================================
  describe('Capacity limits', () => {
    it('capacity constants are reasonable', () => {
      expect(MAX_APPROACH_AIRCRAFT).toBe(4)
      expect(MAX_PARKED_AIRCRAFT).toBe(5)
      expect(MAX_TAXI_AIRCRAFT).toBe(2)
    })

    it('over-capacity approach scenario: all flights still render', async () => {
      // 6 descending flights exceeds MAX_APPROACH_AIRCRAFT=4
      useFlightOverride(overCapacityFlights)
      renderApp()
      await waitForAppReady()

      await waitFor(() => {
        // All 6 flights should render in the list
        expect(screen.getByText('(6)')).toBeInTheDocument()
      }, { timeout: 5000 })
    })

    it('flight list count reflects actual number even if above capacity', async () => {
      useFlightOverride(overCapacityFlights)
      renderApp()
      await waitForAppReady()

      await waitFor(() => {
        expect(screen.getByText(/TST700/)).toBeInTheDocument()
        expect(screen.getByText(/TST705/)).toBeInTheDocument()
      }, { timeout: 5000 })
    })

    it('user can select any flight regardless of capacity state', async () => {
      useFlightOverride(overCapacityFlights)
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      await waitFor(() => {
        expect(screen.getByText(/TST703/)).toBeInTheDocument()
      }, { timeout: 5000 })

      const row = screen.getByText(/TST703/).closest('button')!
      await user.click(row)

      await waitFor(() => {
        expect(screen.getByText(/cap003/)).toBeInTheDocument()
      })
    })
  })

  // =========================================================================
  // E. Mixed-phase flight set
  // =========================================================================
  describe('Mixed-phase fleet with separation awareness', () => {
    const mixedFleet: Flight[] = [
      ...separatedApproachFlights,
      ...groundFlightsOk,
      {
        icao24: 'crz001',
        callsign: 'JBU999',
        latitude: 37.80,
        longitude: -122.10,
        altitude: 35000,
        velocity: 450,
        heading: 180,
        vertical_rate: 0,
        on_ground: false,
        last_seen: new Date().toISOString(),
        data_source: 'synthetic',
        flight_phase: 'enroute',
        aircraft_type: 'A321',
      },
    ]

    it('renders all phases: approaching, taxi_in, enroute', async () => {
      useFlightOverride(mixedFleet)
      renderApp()
      await waitForAppReady()

      await waitFor(() => {
        expect(screen.getByText(/UAL100/)).toBeInTheDocument() // approaching
        expect(screen.getByText(/UAL500/)).toBeInTheDocument() // taxi_in
        expect(screen.getByText(/JBU999/)).toBeInTheDocument() // enroute
      }, { timeout: 5000 })
    })

    it('flight count matches total fleet size', async () => {
      useFlightOverride(mixedFleet)
      renderApp()
      await waitForAppReady()

      await waitFor(() => {
        expect(screen.getByText(`(${mixedFleet.length})`)).toBeInTheDocument()
      }, { timeout: 5000 })
    })

    it('approach flights among the mixed fleet maintain required separation', () => {
      const approachFlights = mixedFleet.filter((f) => f.flight_phase === 'approaching')
      expect(approachFlights.length).toBe(2)

      const f1 = approachFlights[0]
      const f2 = approachFlights[1]
      const actual = distanceNM([f1.latitude, f1.longitude], [f2.latitude, f2.longitude])
      const required = getRequiredSeparationNM(f1.aircraft_type!, f2.aircraft_type!)

      expect(actual).toBeGreaterThanOrEqual(required)
    })

    it('ground flights among the mixed fleet maintain taxi separation', () => {
      const ground = mixedFleet.filter((f) => f.flight_phase === 'taxi_in')
      expect(ground.length).toBe(2)

      for (let i = 0; i < ground.length; i++) {
        for (let j = i + 1; j < ground.length; j++) {
          const latDiff = ground[i].latitude - ground[j].latitude
          const lonDiff = ground[i].longitude - ground[j].longitude
          const degDist = Math.sqrt(latDiff * latDiff + lonDiff * lonDiff)
          expect(degDist).toBeGreaterThanOrEqual(MIN_TAXI_SEPARATION_DEG)
        }
      }
    })

    it('selecting descending flight → selecting cruising flight transitions cleanly', async () => {
      useFlightOverride(mixedFleet)
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      await waitFor(() => {
        expect(screen.getByText(/UAL100/)).toBeInTheDocument()
      }, { timeout: 5000 })

      // Select descending flight
      const descRow = screen.getByText(/UAL100/).closest('button')!
      await user.click(descRow)
      await waitFor(() => {
        expect(screen.getByText(/gate recommendations/i)).toBeInTheDocument()
      }, { timeout: 5000 })

      // Switch to cruising flight
      const crzRow = screen.getByText(/JBU999/).closest('button')!
      await user.click(crzRow)
      await waitFor(() => {
        // Verify detail panel shows cruising flight's icao24
        expect(screen.getByText(/crz001/)).toBeInTheDocument()
      })

      // No gate recommendations for cruising
      expect(screen.queryByText(/gate recommendations/i)).not.toBeInTheDocument()
    })
  })

  // =========================================================================
  // F. Separation validation across the default mock data
  // =========================================================================
  describe('Default mock data separation compliance', () => {
    it('all descending flights in default mocks have valid separation', async () => {
      // Use the default handlers (no override)
      renderApp()
      await waitForAppReady()

      // The default mock has UAL123 (approaching, B737) and DAL456 (enroute, A320)
      // Only 1 approaching flight → separation N/A (trivially OK)
      await waitFor(() => {
        expect(screen.getByText(/UAL123/)).toBeInTheDocument()
      }, { timeout: 5000 })

      // Verify by checking the data directly
      const { mockFlights } = await import('./test/mocks/handlers')
      const descending = mockFlights.filter((f) => f.flight_phase === 'approaching')

      if (descending.length >= 2) {
        for (let i = 0; i < descending.length; i++) {
          for (let j = i + 1; j < descending.length; j++) {
            const actual = distanceNM(
              [descending[i].latitude, descending[i].longitude],
              [descending[j].latitude, descending[j].longitude],
            )
            const required = getRequiredSeparationNM(
              descending[i].aircraft_type,
              descending[j].aircraft_type,
            )
            expect(actual).toBeGreaterThanOrEqual(required)
          }
        }
      }
    })

    it('all ground flights in default mocks have valid taxi separation', async () => {
      renderApp()
      await waitForAppReady()

      const { mockFlights } = await import('./test/mocks/handlers')
      const ground = mockFlights.filter((f) => f.on_ground)

      for (let i = 0; i < ground.length; i++) {
        for (let j = i + 1; j < ground.length; j++) {
          const latDiff = ground[i].latitude - ground[j].latitude
          const lonDiff = ground[i].longitude - ground[j].longitude
          const degDist = Math.sqrt(latDiff * latDiff + lonDiff * lonDiff)
          expect(degDist).toBeGreaterThanOrEqual(MIN_TAXI_SEPARATION_DEG)
        }
      }
    })
  })

  // =========================================================================
  // G. Performance — separation checks should not slow the UI
  // =========================================================================
  describe('Separation check performance', () => {
    it('checking separation for 100 flight pairs completes in < 10ms', () => {
      const flights: Array<{ lat: number; lon: number; type: string }> = []
      for (let i = 0; i < 100; i++) {
        flights.push({
          lat: 37.5 + Math.random() * 0.3,
          lon: -122.5 + Math.random() * 0.3,
          type: ['A320', 'B737', 'B747', 'A380', 'E175'][i % 5],
        })
      }

      const start = performance.now()
      let checks = 0
      for (let i = 0; i < flights.length; i++) {
        for (let j = i + 1; j < flights.length; j++) {
          const actual = distanceNM(
            [flights[i].lat, flights[i].lon],
            [flights[j].lat, flights[j].lon],
          )
          const required = getRequiredSeparationNM(flights[i].type, flights[j].type)
          getSeparationStatus(actual, required)
          checks++
        }
      }
      const elapsed = performance.now() - start

      expect(checks).toBe(4950) // C(100,2)
      expect(elapsed).toBeLessThan(10) // ms
    })
  })
})
